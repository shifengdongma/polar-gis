"""Tests for the bulk S-57 SLD style refresh service and admin endpoint."""

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
from app.services.s57_style_refresh import refresh_s57_layer_styles


class StubGeoServer:
    """GeoServerClient stand-in recording style publish / cache truncate calls."""

    def __init__(self) -> None:
        self.publish_style_calls: list[tuple[str, str]] = []
        self.set_default_style_calls: list[tuple[str, str]] = []
        self.truncate_calls: list[str] = []
        self.fail_truncate_layers: set[str] = set()

    def publish_style(self, style_name: str, sld: str) -> None:
        self.publish_style_calls.append((style_name, sld))

    def set_default_style(self, layer_name: str, style_name: str) -> None:
        self.set_default_style_calls.append((layer_name, style_name))

    def truncate_layer_cache(self, layer_name: str) -> None:
        if layer_name in self.fail_truncate_layers:
            raise RuntimeError(f"stub truncate failure for {layer_name}")
        self.truncate_calls.append(layer_name)


def _seed_s57_layer(
    db: Session,
    *,
    code: str,
    source_layer: str,
    geometry_type: str = "Point",
    s57: dict | None = None,
    status: str = LayerStatus.AVAILABLE.value,
) -> Layer:
    admin_id = db.scalar(select(User.id).where(User.username == "admin"))
    dataset = Dataset(
        code=f"ds_{code}",
        name=code,
        data_type=DatasetType.S57.value,
        created_by=admin_id,
    )
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
        name=source_layer,
        geometry_type=geometry_type,
        status=status,
        geoserver_workspace="polar_gis",
        geoserver_layer_name=code,
        allowed_fields=[],
        metadata_json={
            "sourceLayer": source_layer,
            "s57": s57 or {"objectClass": source_layer.upper(), "styleMapped": True},
        },
    )
    db.add(layer)
    db.flush()
    return layer


class TestRefreshS57LayerStyles:
    def test_refreshes_changed_layers_and_is_idempotent(
        self, db_session: Session
    ) -> None:
        _seed_s57_layer(db_session, code="SOUNDG_A", source_layer="SOUNDG")
        _seed_s57_layer(
            db_session, code="DEPCNT_B", source_layer="DEPCNT", geometry_type="Line String"
        )
        stub = StubGeoServer()

        first = refresh_s57_layer_styles(
            db_session, geoserver=stub, settings=Settings()
        )
        second = refresh_s57_layer_styles(
            db_session, geoserver=stub, settings=Settings()
        )

        assert first == {"checked": 2, "updated": 2, "failed": 0}
        # second run: hashes now match the deployed SLDs → nothing to do
        assert second == {"checked": 2, "updated": 0, "failed": 0}
        assert {name for name, _ in stub.publish_style_calls} == {
            "s57_sounding",
            "s57_contour",
        }
        assert len(stub.publish_style_calls) == 2
        assert sorted(stub.truncate_calls) == ["DEPCNT_B", "SOUNDG_A"]

    def test_skips_unmapped_and_disabled_layers(self, db_session: Session) -> None:
        _seed_s57_layer(db_session, code="SOUNDG_C", source_layer="SOUNDG")
        _seed_s57_layer(
            db_session, code="DSID_D", source_layer="DSID", geometry_type=None
        )
        _seed_s57_layer(
            db_session,
            code="LIGHTS_E",
            source_layer="LIGHTS",
            status=LayerStatus.DISABLED.value,
        )
        stub = StubGeoServer()

        result = refresh_s57_layer_styles(
            db_session, geoserver=stub, settings=Settings()
        )

        # disabled layer excluded from scan; unmapped layer checked but untouched
        assert result == {"checked": 2, "updated": 1, "failed": 0}
        assert [name for name, _ in stub.publish_style_calls] == ["s57_sounding"]
        assert stub.truncate_calls == ["SOUNDG_C"]

    def test_truncate_failure_is_best_effort(self, db_session: Session) -> None:
        _seed_s57_layer(db_session, code="SOUNDG_F", source_layer="SOUNDG")
        _seed_s57_layer(db_session, code="WRECKS_G", source_layer="WRECKS")
        stub = StubGeoServer()
        stub.fail_truncate_layers = {"SOUNDG_F"}

        result = refresh_s57_layer_styles(
            db_session, geoserver=stub, settings=Settings()
        )

        assert result["checked"] == 2
        assert result["updated"] == 2  # both re-published; truncate never aborts
        assert result["failed"] == 0
        assert stub.truncate_calls == ["WRECKS_G"]


class TestRefreshS57StylesAdminEndpoint:
    def test_requires_admin_and_returns_refresh_result(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        user_headers: dict[str, str],
        monkeypatch,
    ) -> None:
        captured: list[Session] = []

        def fake_refresh(db: Session, **kwargs: object) -> dict:
            captured.append(db)
            return {"checked": 5, "updated": 3, "failed": 0}

        monkeypatch.setattr(system_api, "refresh_s57_layer_styles", fake_refresh)

        forbidden = client.post("/api/v1/admin/styles/refresh-s57", headers=user_headers)
        assert forbidden.status_code == 403

        ok = client.post("/api/v1/admin/styles/refresh-s57", headers=admin_headers)
        assert ok.status_code == 200, ok.text
        assert ok.json() == {"checked": 5, "updated": 3, "failed": 0}
        assert len(captured) == 1
