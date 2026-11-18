"""Tests for the GWC EPSG:3413 backfill service and admin endpoint."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import system as system_api
from app.core.config import Settings
from app.models import (
    BaseMap,
    Dataset,
    DatasetType,
    DatasetVersion,
    Layer,
    LayerStatus,
    User,
    VersionStatus,
)
from app.services.gwc_backfill import (
    ensure_gwc_3413_backfill,
    ensure_overview_basemap_config,
)
from app.services.wmts_tiles import overview_wmts_tile_template


class StubGeoServer:
    """GeoServerClient stand-in recording gridset/GWC calls."""

    def __init__(self) -> None:
        self.gridset_calls: list[tuple[str, str, list[float]]] = []
        self.gwc_puts: list[str] = []
        self.gets: list[tuple[str, str]] = []
        self.responses: dict[str, dict] = {}

    def ensure_gridset(self, gridset_name: str, crs: str, extent: list[float]) -> None:
        self.gridset_calls.append((gridset_name, crs, extent))

    def ensure_gwc_layer(
        self,
        layer_name: str,
        gridsets: list[str] | None = None,
        mime_formats: list[str] | None = None,
    ) -> None:
        self.gwc_puts.append(layer_name)

    def get_gwc_layer(self, layer_name: str) -> dict | None:
        key = f"polar_gis:{layer_name}"
        self.gets.append(("GET", f"gwc/rest/layers/{key}.json"))
        return self.responses.get(key)

    def set_layer_config(self, layer_name: str, grid_subsets: list[str]) -> None:
        self.responses[f"polar_gis:{layer_name}"] = {
            "GeoServerLayer": {
                "name": f"polar_gis:{layer_name}",
                "enabled": True,
                "gridSubsets": [{"gridSetName": name} for name in grid_subsets],
            }
        }


def _seed_layer(
    db: Session,
    *,
    code: str,
    data_type: str = DatasetType.S57.value,
    status: str = LayerStatus.AVAILABLE.value,
    layer_name: str | None = None,
    deleted: bool = False,
) -> Layer:
    admin_id = db.scalar(select(User.id).where(User.username == "admin"))
    dataset = Dataset(code=f"ds_{code}", name=code, data_type=data_type, created_by=admin_id)
    db.add(dataset)
    db.flush()
    version = DatasetVersion(
        dataset_id=dataset.id,
        version_no=1,
        source_format="000",
        status=VersionStatus.VALID.value,
        content_hash="0" * 64,
        metadata_json={},
    )
    db.add(version)
    db.flush()
    dataset.current_version_id = version.id
    db.flush()
    layer = Layer(
        dataset_version_id=version.id,
        code=code,
        name=code,
        geometry_type="Multi Polygon",
        status=status,
        geoserver_workspace="polar_gis",
        geoserver_layer_name=layer_name or code,
        allowed_fields=[],
    )
    if deleted:
        layer.deleted_at = datetime.now(UTC)
    db.add(layer)
    db.flush()
    return layer


class TestBackfillFunction:
    def test_puts_gridset_and_configures_layer_missing_3413(
        self, db_session: Session
    ) -> None:
        _seed_layer(db_session, code="DEPARE")
        stub = StubGeoServer()
        stub.set_layer_config("DEPARE", ["EPSG:900913", "EPSG:4326"])

        result = ensure_gwc_3413_backfill(
            db_session,
            geoserver=stub,  # type: ignore[arg-type]
            settings=Settings(gwc_3413_backfill=True),
        )

        assert result == {"checked": 1, "updated": 1, "skipped": False}
        assert len(stub.gridset_calls) == 1
        assert stub.gridset_calls[0] == (
            "EPSG:3413",
            "EPSG:3413",
            [-4194304.0, -4194304.0, 4194304.0, 4194304.0],
        )
        assert stub.gwc_puts == ["DEPARE"]
        assert stub.gets == [("GET", "gwc/rest/layers/polar_gis:DEPARE.json")]

    def test_skips_layer_already_having_3413(self, db_session: Session) -> None:
        _seed_layer(db_session, code="LIGHTS")
        stub = StubGeoServer()
        stub.set_layer_config("LIGHTS", ["EPSG:900913", "EPSG:4326", "EPSG:3413"])

        result = ensure_gwc_3413_backfill(
            db_session,
            geoserver=stub,  # type: ignore[arg-type]
            settings=Settings(gwc_3413_backfill=True),
        )

        assert result == {"checked": 1, "updated": 0, "skipped": False}
        assert stub.gwc_puts == []

    def test_configures_layer_not_yet_in_gwc(self, db_session: Session) -> None:
        _seed_layer(db_session, code="WRECKS")
        stub = StubGeoServer()  # no responses → GET returns 404

        result = ensure_gwc_3413_backfill(
            db_session,
            geoserver=stub,  # type: ignore[arg-type]
            settings=Settings(gwc_3413_backfill=True),
        )

        assert result == {"checked": 1, "updated": 1, "skipped": False}
        assert stub.gwc_puts == ["WRECKS"]

    def test_ignores_non_s57_unavailable_and_deleted_layers(
        self, db_session: Session
    ) -> None:
        _seed_layer(db_session, code="RASTER_X", data_type=DatasetType.RASTER.value)
        _seed_layer(db_session, code="SOUNDG", status=LayerStatus.DISABLED.value)
        _seed_layer(db_session, code="DEPARE_OLD", deleted=True)
        _seed_layer(db_session, code="OK_LAYER")
        stub = StubGeoServer()
        stub.set_layer_config("OK_LAYER", ["EPSG:900913"])

        result = ensure_gwc_3413_backfill(
            db_session,
            geoserver=stub,  # type: ignore[arg-type]
            settings=Settings(gwc_3413_backfill=True),
        )

        assert result == {"checked": 1, "updated": 1, "skipped": False}
        assert stub.gwc_puts == ["OK_LAYER"]
        assert stub.gets == [("GET", "gwc/rest/layers/polar_gis:OK_LAYER.json")]

    def test_disabled_by_gwc_3413_backfill_env(self, db_session: Session) -> None:
        _seed_layer(db_session, code="DEPARE")
        stub = StubGeoServer()

        result = ensure_gwc_3413_backfill(
            db_session,
            geoserver=stub,  # type: ignore[arg-type]
            settings=Settings(gwc_3413_backfill=False),
        )

        assert result == {"checked": 0, "updated": 0, "skipped": True}
        assert stub.gridset_calls == []
        assert stub.gets == []
        assert stub.gwc_puts == []


class TestOverviewBasemapConfig:
    def test_adds_missing_3413_grid_subset_to_layer_group(self, db_session: Session) -> None:
        stub = StubGeoServer()
        stub.set_layer_config("polar_global_enc_overview", ["EPSG:900913", "EPSG:4326"])

        result = ensure_overview_basemap_config(
            db_session,
            geoserver=stub,  # type: ignore[arg-type]
            settings=Settings(),
        )

        assert result["group"] == "updated"
        assert stub.gwc_puts == ["polar_global_enc_overview"]
        assert stub.gridset_calls == [
            ("EPSG:3413", "EPSG:3413", [-4194304.0, -4194304.0, 4194304.0, 4194304.0])
        ]

    def test_leaves_fully_configured_group_unchanged(self, db_session: Session) -> None:
        stub = StubGeoServer()
        stub.set_layer_config(
            "polar_global_enc_overview", ["EPSG:900913", "EPSG:4326", "EPSG:3413"]
        )

        result = ensure_overview_basemap_config(
            db_session,
            geoserver=stub,  # type: ignore[arg-type]
            settings=Settings(),
        )

        assert result["group"] == "unchanged"
        assert stub.gwc_puts == []

    def test_skips_group_without_gwc_config(self, db_session: Session) -> None:
        stub = StubGeoServer()  # GET → 404

        result = ensure_overview_basemap_config(
            db_session,
            geoserver=stub,  # type: ignore[arg-type]
            settings=Settings(),
        )

        assert result["group"] == "missing"
        assert stub.gwc_puts == []

    def test_rewrites_legacy_capabilities_templates(self, db_session: Session) -> None:
        legacy = "/geoserver/gwc/service/wmts?REQUEST=GetCapabilities"
        db_session.add_all(
            [
                BaseMap(
                    name="全球海图概览底图",
                    map_type="WMTS",
                    url_template=legacy,
                    crs="EPSG:3857",
                ),
                BaseMap(
                    name="全球海图概览底图（北极）",
                    map_type="WMTS",
                    url_template=legacy,
                    crs="EPSG:3413",
                ),
            ]
        )
        db_session.commit()
        stub = StubGeoServer()

        result = ensure_overview_basemap_config(
            db_session,
            geoserver=stub,  # type: ignore[arg-type]
            settings=Settings(),
        )

        assert result["templatesUpdated"] == 2
        rows = {row.crs: row for row in db_session.scalars(select(BaseMap)).all()}
        assert "REQUEST=GetTile" in rows["EPSG:3857"].url_template
        assert "TILEMATRIXSET=EPSG:900913" in rows["EPSG:3857"].url_template
        assert "TILEMATRIXSET=EPSG:3413" in rows["EPSG:3413"].url_template
        assert "TILEMATRIX=EPSG:3413:{z}" in rows["EPSG:3413"].url_template
        assert "GetCapabilities" not in rows["EPSG:3413"].url_template

    def test_does_not_clobber_admin_custom_url(self, db_session: Session) -> None:
        custom = "https://tiles.example.test/wmts/{z}/{x}/{y}.png"
        db_session.add(
            BaseMap(
                name="全球海图概览底图",
                map_type="WMTS",
                url_template=custom,
                crs="EPSG:3857",
            )
        )
        db_session.commit()
        stub = StubGeoServer()

        result = ensure_overview_basemap_config(
            db_session,
            geoserver=stub,  # type: ignore[arg-type]
            settings=Settings(),
        )

        assert result["templatesUpdated"] == 0
        row = db_session.scalar(select(BaseMap).where(BaseMap.crs == "EPSG:3857"))
        assert row is not None
        assert row.url_template == custom


def test_overview_wmts_tile_template_targets_gwc_matrix_sets() -> None:
    url = overview_wmts_tile_template("/geoserver", "polar_gis", "EPSG:3413")
    assert url.startswith("/geoserver/gwc/service/wmts?")
    assert "LAYER=polar_gis:polar_global_enc_overview" in url
    assert "TILEMATRIXSET=EPSG:3413" in url
    assert "TILEMATRIX=EPSG:3413:{z}" in url
    assert "TILEROW={y}" in url
    assert "TILECOL={x}" in url

    with pytest.raises(ValueError):
        overview_wmts_tile_template("/geoserver", "polar_gis", "EPSG:4326")


class TestBackfillAdminEndpoint:
    def test_requires_admin_and_returns_backfill_result(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        user_headers: dict[str, str],
        db_session: Session,
        monkeypatch,
    ) -> None:
        captured: list[Session] = []

        def fake_backfill(db: Session, **kwargs: object) -> dict:
            captured.append(db)
            return {"checked": 3, "updated": 1, "skipped": False}

        monkeypatch.setattr(system_api, "ensure_gwc_3413_backfill", fake_backfill)

        forbidden = client.post("/api/v1/admin/gwc/backfill", headers=user_headers)
        assert forbidden.status_code == 403

        ok = client.post("/api/v1/admin/gwc/backfill", headers=admin_headers)
        assert ok.status_code == 200, ok.text
        assert ok.json() == {"checked": 3, "updated": 1, "skipped": False}
        assert len(captured) == 1
