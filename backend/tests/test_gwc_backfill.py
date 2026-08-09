"""Tests for the GWC EPSG:3413 backfill service and admin endpoint."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import system as system_api
from app.core.config import Settings
from app.models import (
    Dataset,
    DatasetType,
    DatasetVersion,
    Layer,
    LayerStatus,
    User,
    VersionStatus,
)
from app.services.gwc_backfill import ensure_gwc_3413_backfill


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class StubGeoServer:
    """GeoServerClient stand-in recording gridset/GWC calls."""

    def __init__(self) -> None:
        self.gridset_calls: list[tuple[str, str, list[float]]] = []
        self.gwc_puts: list[str] = []
        self.gets: list[tuple[str, str]] = []
        self.responses: dict[str, FakeResponse] = {}

    def ensure_gridset(self, gridset_name: str, crs: str, extent: list[float]) -> None:
        self.gridset_calls.append((gridset_name, crs, extent))

    def ensure_gwc_layer(
        self,
        layer_name: str,
        gridsets: list[str] | None = None,
        mime_formats: list[str] | None = None,
    ) -> None:
        self.gwc_puts.append(layer_name)

    def _request(
        self,
        method: str,
        path: str,
        allowed_statuses: set[int] | None = None,
        **kwargs: object,
    ) -> FakeResponse:
        self.gets.append((method, path))
        key = path.split("gwc/layers/", 1)[1].rstrip(".json")
        return self.responses.get(key, FakeResponse(404))

    def set_layer_config(self, layer_name: str, grid_subsets: list[str]) -> None:
        self.responses[f"polar_gis:{layer_name}"] = FakeResponse(
            200,
            {
                "GeoServerLayer": {
                    "name": f"polar_gis:{layer_name}",
                    "enabled": True,
                    "gridSubsets": [{"gridSetName": name} for name in grid_subsets],
                }
            },
        )


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
        stub.set_layer_config("DEPARE", ["EPSG:3857", "EPSG:4326"])

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
        assert stub.gets == [("GET", "gwc/layers/polar_gis:DEPARE.json")]

    def test_skips_layer_already_having_3413(self, db_session: Session) -> None:
        _seed_layer(db_session, code="LIGHTS")
        stub = StubGeoServer()
        stub.set_layer_config("LIGHTS", ["EPSG:3857", "EPSG:4326", "EPSG:3413"])

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
        stub.set_layer_config("OK_LAYER", ["EPSG:3857"])

        result = ensure_gwc_3413_backfill(
            db_session,
            geoserver=stub,  # type: ignore[arg-type]
            settings=Settings(gwc_3413_backfill=True),
        )

        assert result == {"checked": 1, "updated": 1, "skipped": False}
        assert stub.gwc_puts == ["OK_LAYER"]
        assert stub.gets == [("GET", "gwc/layers/polar_gis:OK_LAYER.json")]

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
