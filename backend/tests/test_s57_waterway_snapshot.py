import json
import shutil
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.models import Project, User
from app.services import s57_waterway_export as export
from app.services.s57_waterway_catalog import classify_waterway
from app.services.s57_waterways import (
    WaterwayLayerRef,
    WaterwayResolution,
    build_waterway_export_batch_sql,
)


def make_layer(*, key_column="ogc_fid", key_type="int", geometry=True):
    return WaterwayLayerRef(
        layer_id=uuid4(),
        layer_code="s57_test_1_fairwy",
        layer_name="FAIRWY",
        dataset_id=uuid4(),
        dataset_code="s57_test",
        dataset_name="S-57 海图 TEST",
        version_no=1,
        source_cell="TEST",
        object_class="FAIRWY",
        rule=classify_waterway("FAIRWY"),
        source_table="geo.ds_test_v1_fairwy",
        geometry_type="MultiLineString" if geometry else None,
        fields=("objnam", "nobjnm", "inform", "status"),
        key_column=key_column,
        key_type=key_type,
        geometry_column="geom" if geometry else None,
        feature_count=3,
        available=True,
        queryable=True,
        renderable=geometry,
        reason=None,
        updated_at=None,
    )


def payload(**overrides):
    return SimpleNamespace(
        keyword=overrides.get("keyword"),
        bbox=overrides.get("bbox"),
        include_auxiliary=overrides.get("include_auxiliary", False),
        object_classes=overrides.get("object_classes", ["FAIRWY"]),
        name=overrides.get("name"),
        max_features=overrides.get("max_features"),
    )


def published_project(db, code):
    user = db.scalar(select(User))
    project = Project(
        code=code,
        name="Snapshot Project",
        status="published",
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def feature():
    return {
        "type": "Feature",
        "id": "stable-id",
        "geometry": {"type": "LineString", "coordinates": [[120.0, 75.0], [121.0, 75.5]]},
        "properties": {
            "objectClass": "FAIRWY",
            "objectName": "Test Fairway",
            "objectNameZh": "航道",
            "group": "fairway_route",
            "groupNameZh": "航道与推荐路线",
            "auxiliary": False,
            "sourceLayerId": "layer-1",
            "sourceLayerCode": "s57_test_1_fairwy",
            "sourceLayerName": "FAIRWY",
            "sourceDatasetId": "dataset-1",
            "sourceDatasetCode": "s57_test",
            "sourceDatasetName": "S-57 海图 TEST",
            "sourceVersionId": "old-version",
            "sourceVersionNo": 1,
            "sourceCell": "TEST",
            "originalAttributes": {"objnam": "Test Fairway", "drval1": 12.5},
        },
    }


def source_datasets():
    return [
        {
            "datasetId": "dataset-1",
            "datasetCode": "s57_test",
            "datasetName": "S-57 海图 TEST",
            "versionId": "old-version",
            "versionNo": 1,
            "sourceCell": "TEST",
            "layerIds": ["layer-1"],
            "contentHash": "a" * 64,
        }
    ]


def write_fixture(project_id, root=None):
    return export.write_snapshot(
        project_id,
        name="测试成果",
        features=[feature()],
        object_classes=["FAIRWY"],
        source_datasets=source_datasets(),
        source_version_ids=["old-version"],
        source_content_hashes={"old-version": "a" * 64},
        filters={"keyword": None, "objectClasses": ["FAIRWY"]},
        warnings=[],
        truncated=False,
        root=root,
    )


def test_export_batch_sql_uses_keyset_and_raw_attributes():
    ref = make_layer()
    sql, params = build_waterway_export_batch_sql(
        ref, payload(keyword="Jinghang"), after_key="5", limit=100
    )
    assert "UNION ALL" not in sql
    assert "ST_AsGeoJSON(ST_Transform(w.\"geom\", 4326))" in sql
    assert "to_jsonb(w.*) - CAST(:geom_field AS text)" in sql
    assert "w.\"ogc_fid\" > CAST(:after_key AS BIGINT)" in sql
    assert "ORDER BY w.\"ogc_fid\" LIMIT :limit" in sql
    assert params["keyword_0"] == "Jinghang"
    assert params["after_key"] == "5"
    assert params["geom_field"] == "geom"
    assert params["limit"] == 100


def test_export_batch_sql_text_key_and_non_spatial_bbox():
    text_layer = make_layer(key_column="rcid", key_type="text")
    sql, _ = build_waterway_export_batch_sql(
        text_layer, payload(), after_key="abc", limit=20
    )
    assert "w.\"rcid\" > :after_key" in sql
    assert "BIGINT" not in sql

    non_spatial = make_layer(geometry=False)
    sql, params = build_waterway_export_batch_sql(
        non_spatial, payload(bbox=(10.0, 70.0, 20.0, 80.0)), after_key=None, limit=20
    )
    assert sql == ""
    assert params == {}


def test_write_and_read_snapshot_roundtrip(tmp_path):
    project_id = uuid4()
    manifest = write_fixture(project_id, root=tmp_path)
    assert manifest["stale"] is False
    assert manifest["featureCount"] == 1
    assert manifest["crs"] == "EPSG:4326"
    assert manifest["schemaVersion"] == export.SNAPSHOT_SCHEMA_VERSION
    assert manifest["objectClasses"] == ["FAIRWY"]

    snapshot_dir = tmp_path / str(project_id) / manifest["snapshotId"]
    geojson = json.loads((snapshot_dir / export.GEOJSON_FILENAME).read_text(encoding="utf-8"))
    assert geojson["type"] == "FeatureCollection"
    assert geojson["features"][0]["geometry"]["type"] == "LineString"
    assert geojson["features"][0]["properties"]["originalAttributes"]["drval1"] == 12.5
    stored = json.loads((snapshot_dir / export.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert stored["sourceVersionIds"] == ["old-version"]
    assert not any(path.name.endswith(".tmp") for path in (tmp_path / str(project_id)).iterdir())

    items, warnings = export.list_snapshots(project_id, root=tmp_path)
    assert warnings == []
    assert [item["snapshotId"] for item in items] == [manifest["snapshotId"]]
    loaded = export.load_snapshot_manifest(project_id, manifest["snapshotId"], root=tmp_path)
    assert loaded["featureCount"] == 1
    assert export.mark_snapshot_stale(loaded, {"other-version"})["stale"] is True
    assert export.mark_snapshot_stale(loaded, {"old-version"})["stale"] is False


def test_list_snapshots_skips_corrupt_manifest(tmp_path):
    project_id = uuid4()
    broken = tmp_path / str(project_id) / "broken"
    broken.mkdir(parents=True)
    (broken / export.MANIFEST_FILENAME).write_text("{not-json", encoding="utf-8")
    items, warnings = export.list_snapshots(project_id, root=tmp_path)
    assert items == []
    assert warnings and "broken" in warnings[0]


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeDb:
    """Minimal Session stand-in for the keyset extraction loop (no PostGIS)."""

    def __init__(self, batches):
        self.batches = batches
        self.binds = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    def get_bind(self):
        return self.binds

    def execute(self, _sql, params):
        return FakeResult(self.batches.get(params.get("after_key"), []))


def test_create_snapshot_extracts_all_keyset_batches(tmp_path, monkeypatch):
    layer = make_layer()
    layer = WaterwayLayerRef(
        **{
            **layer.__dict__,
            "version_id": uuid4(),
            "content_hash": "b" * 64,
        }
    )
    monkeypatch.setattr(
        export,
        "resolve_waterway_layers",
        lambda _db, _project_id: WaterwayResolution(layers=(layer,), warnings=()),
    )
    settings = Settings(
        storage_root=tmp_path,
        temp_root=tmp_path / "temp",
        s57_waterway_snapshot_root=tmp_path / "snapshots",
        s57_waterway_snapshot_batch_size=2,
    )
    monkeypatch.setattr(export, "get_settings", lambda: settings)

    def row(number: int):
        return {
            "feature_key": str(number),
            "name": f"航道 {number}",
            "geometry": json.dumps(
                {
                    "type": "MultiLineString",
                    "coordinates": [[[120.0 + number, 75.0], [121.0 + number, 75.5]]],
                }
            ),
            "raw_attributes": {"objnam": f"Fairway {number}", "drval1": 10 + number},
        }

    db = FakeDb({None: [row(1), row(2)], "2": [row(3)]})
    project_id = uuid4()
    manifest = export.create_waterway_snapshot(
        db,
        project_id,
        payload(name="批次测试", object_classes=["FAIRWY"]),
    )
    assert manifest["featureCount"] == 3
    assert manifest["truncated"] is False
    assert manifest["sourceVersionIds"] == [str(layer.version_id)]
    assert manifest["sourceContentHashes"][str(layer.version_id)] == "b" * 64
    assert manifest["sourceDatasets"][0]["layerIds"] == [str(layer.layer_id)]

    snapshot_dir = (
        settings.resolved_s57_waterway_snapshot_root
        / str(project_id)
        / manifest["snapshotId"]
    )
    geojson = json.loads((snapshot_dir / export.GEOJSON_FILENAME).read_text(encoding="utf-8"))
    assert len(geojson["features"]) == 3
    assert {
        feature["geometry"]["type"] for feature in geojson["features"]
    } == {"MultiLineString"}
    assert geojson["features"][0]["properties"]["originalAttributes"]["drval1"] == 11


def test_snapshot_routes_create_list_detail_download(
    client, db_session, user_headers, monkeypatch
):
    project = published_project(db_session, f"snapshot-{uuid4().hex[:8]}")
    settings = get_settings()
    project_dir = settings.resolved_s57_waterway_snapshot_root / str(project.id)
    from app.api import s57_waterways as api

    def fake_create(db, project_id, _payload):
        return write_fixture(project_id)

    monkeypatch.setattr(api.snapshot_service, "create_waterway_snapshot", fake_create)

    url = f"/api/v1/projects/{project.id}/s57-waterways/snapshots"
    try:
        created = client.post(url, headers=user_headers, json={"objectClasses": ["FAIRWY"]})
        assert created.status_code == 201, created.text
        manifest = created.json()
        assert manifest["snapshotId"]
        assert manifest["featureCount"] == 1
        snapshot_id = manifest["snapshotId"]

        listed = client.get(url, headers=user_headers)
        assert listed.status_code == 200, listed.text
        payload_json = listed.json()
        assert [item["snapshotId"] for item in payload_json["items"]] == [snapshot_id]
        assert payload_json["items"][0]["stale"] is True

        detail = client.get(f"{url}/{snapshot_id}", headers=user_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["sourceVersionIds"] == ["old-version"]

        download = client.get(f"{url}/{snapshot_id}/download", headers=user_headers)
        assert download.status_code == 200, download.text
        assert download.headers["content-type"].startswith("application/geo+json")
        assert "waterways-" in download.headers["content-disposition"]
        downloaded = download.json()
        assert downloaded["features"][0]["properties"]["objectClass"] == "FAIRWY"

        invalid = client.get(f"{url}/bad!id", headers=user_headers)
        assert invalid.status_code == 404
    finally:
        shutil.rmtree(project_dir, ignore_errors=True)
