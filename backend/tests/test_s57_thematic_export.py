import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.services import s57_thematic_export as export
from app.services.s57_project_layers import ProjectS57LayerRef
from app.services.s57_thematic_catalog import (
    ThematicResolution,
    build_thematic_catalog,
)


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.binds = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    def get_bind(self):
        return self.binds

    def rollback(self):
        return None

    def execute(self, _sql, params):
        after_key = params.get("after_key")
        limit = int(params.get("limit") or len(self.rows))
        rows = self.rows
        if after_key is not None:
            rows = [
                row
                for row in rows
                if int(row["feature_key"]) > int(after_key)
            ]
        return FakeResult(rows[:limit])


def soundg_layer() -> ProjectS57LayerRef:
    return ProjectS57LayerRef(
        layer_id=uuid4(),
        layer_code="s57_no1_1_soundg",
        layer_name="SOUNDG",
        dataset_id=uuid4(),
        dataset_code="s57_no1",
        dataset_name="S-57 海图 NO1",
        version_no=1,
        source_cell="NO1",
        object_class="SOUNDG",
        source_table="geo.ds_no1_v1_soundg",
        geometry_type="MultiPoint",
        fields=("objnam", "verdat"),
        key_column="ogc_fid",
        key_type="int",
        geometry_column="geom",
        feature_count=2,
        available=True,
        queryable=True,
        renderable=True,
        reason=None,
        updated_at=None,
        version_id=uuid4(),
        content_hash="c" * 64,
        extent=(10.0, 70.0, 12.0, 72.0),
    )


def resolution(layer, *, depth_preserved=True) -> ThematicResolution:
    return ThematicResolution(
        layers=(layer,),
        warnings=(),
        depth_by_layer={
            str(layer.layer_id): {
                "layerId": str(layer.layer_id),
                "sourceCell": layer.source_cell,
                "geometryNdims": 3 if depth_preserved else 2,
                "zMin": 12.5 if depth_preserved else None,
                "zMax": 18.0 if depth_preserved else None,
                "depthPreserved": depth_preserved,
                "note": None,
            }
        },
        candidate_layer_count=1,
        resolved_layer_count=1,
    )


def rows():
    return [
        {
            "feature_key": "1",
            "geometry": json.dumps(
                {"type": "MultiPoint", "coordinates": [[10.5, 70.5, 12.5]]}
            ),
            "geom_ndim": 3,
            "raw_attributes": {
                "objnam": "Sounding A",
                "verdat": "5",
                "depth": 12.5,
                "objl": "SOUNDG",
            },
        },
        {
            "feature_key": "2",
            "geometry": json.dumps(
                {"type": "MultiPoint", "coordinates": [[11.0, 71.0, 18.0]]}
            ),
            "geom_ndim": 3,
            "raw_attributes": {"objnam": "Sounding B", "objl": "SOUNDG"},
        },
    ]


def payload(**overrides):
    return SimpleNamespace(
        name=overrides.get("name", "depth test"),
        object_classes=overrides.get("object_classes", ["SOUNDG"]),
        bbox=overrides.get("bbox"),
        source_cells=overrides.get("source_cells", []),
        dataset_ids=overrides.get("dataset_ids", []),
        max_features_per_class=overrides.get("max_features_per_class"),
    )


def settings(tmp_path, **overrides):
    return Settings(
        storage_root=tmp_path,
        temp_root=tmp_path / "temp",
        s57_thematic_root=tmp_path / "thematic",
        **overrides,
    )


def test_thematic_catalog_lists_depth_and_other_classes(monkeypatch):
    layer = soundg_layer()
    monkeypatch.setattr(
        export,
        "resolve_thematic_layers",
        lambda _db, _project_id: resolution(layer),
    )
    from app.services import s57_thematic_catalog as catalog

    monkeypatch.setattr(
        catalog,
        "resolve_thematic_layers",
        lambda _db, _project_id: resolution(layer),
    )
    monkeypatch.setattr(
        catalog,
        "_fill_layer_counts",
        lambda _db, _layers: {str(layer.layer_id): 2},
    )
    data = build_thematic_catalog(SimpleNamespace(), uuid4())
    assert data["totalLayerCount"] == 1
    assert data["extractableLayerCount"] == 1
    depth = next(item for item in data["classes"] if item["code"] == "SOUNDG")
    assert depth["category"] == "depth"
    assert depth["layers"][0]["sourceCell"] == "NO1"
    assert depth["layers"][0]["extractable"] is True
    assert data["soundgDepth"]["depthPreserved"] is True


def test_thematic_export_preserves_3d_and_provenance(tmp_path, monkeypatch):
    layer = soundg_layer()
    project_id = uuid4()
    monkeypatch.setattr(
        export,
        "resolve_thematic_layers",
        lambda _db, _project_id: resolution(layer),
    )
    monkeypatch.setattr(export, "get_settings", lambda: settings(tmp_path))

    manifest = export.create_thematic_export(
        FakeDb(rows()), project_id, payload()
    )
    assert manifest["complete"] is True
    assert manifest["featureCount"] == 2
    assert manifest["sourceCells"] == ["NO1"]
    assert len(manifest["files"]) == 1
    file_entry = manifest["files"][0]
    geojson_path = export.thematic_file_path(
        project_id, manifest["exportId"], file_entry["path"]
    )
    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    assert len(data["features"]) == 2
    first = data["features"][0]
    assert first["geometry"]["coordinates"][0] == [10.5, 70.5, 12.5]
    assert first["properties"]["sourceCell"] == "NO1"
    assert first["properties"]["sourceVersionNo"] == 1
    assert first["properties"]["geometryNdim"] == 3
    assert first["properties"]["depthSources"] == [
        "geometry_z",
        "attribute:DEPTH",
    ]
    assert first["properties"]["verticalDatum"] == "5"
    assert manifest["depth"]["depthPreserved"] is True
    assert manifest["preview"]["featureCount"] == 2

    # Manifest hash matches the actual file.
    import hashlib

    assert hashlib.sha256(geojson_path.read_bytes()).hexdigest() == file_entry["sha256"]


def test_thematic_export_marks_per_class_truncation(tmp_path, monkeypatch):
    layer = soundg_layer()
    monkeypatch.setattr(
        export,
        "resolve_thematic_layers",
        lambda _db, _project_id: resolution(layer),
    )
    monkeypatch.setattr(
        export,
        "get_settings",
        lambda: settings(tmp_path, s57_thematic_max_features_per_class=1),
    )
    manifest = export.create_thematic_export(
        FakeDb(rows()), uuid4(), payload()
    )
    assert manifest["truncated"] is True
    assert manifest["complete"] is False
    assert "per_class_cap" in manifest["truncationReasons"]
    assert manifest["featureCount"] == 1


def test_thematic_export_path_traversal_is_rejected(tmp_path, monkeypatch):
    layer = soundg_layer()
    project_id = uuid4()
    monkeypatch.setattr(
        export,
        "resolve_thematic_layers",
        lambda _db, _project_id: resolution(layer),
    )
    monkeypatch.setattr(export, "get_settings", lambda: settings(tmp_path))
    manifest = export.create_thematic_export(
        FakeDb(rows()), project_id, payload()
    )
    with pytest.raises(AppError):
        export.thematic_file_path(
            project_id, manifest["exportId"], "../manifest.json"
        )
    with pytest.raises(AppError):
        export.thematic_file_path(
            project_id, manifest["exportId"], "/etc/passwd"
        )


def test_thematic_zip_contains_manifest_and_data(tmp_path, monkeypatch):
    layer = soundg_layer()
    project_id = uuid4()
    monkeypatch.setattr(
        export,
        "resolve_thematic_layers",
        lambda _db, _project_id: resolution(layer),
    )
    monkeypatch.setattr(export, "get_settings", lambda: settings(tmp_path))
    manifest = export.create_thematic_export(
        FakeDb(rows()), project_id, payload()
    )
    zip_path, filename = export.build_thematic_zip(project_id, manifest["exportId"])
    assert filename.endswith(".zip")
    import zipfile

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "manifest.json" in names
    assert all(entry["path"] in names for entry in manifest["files"])
    zip_path.unlink()


def test_thematic_export_without_features_creates_no_result(tmp_path, monkeypatch):
    layer = soundg_layer()
    monkeypatch.setattr(
        export,
        "resolve_thematic_layers",
        lambda _db, _project_id: resolution(layer),
    )
    monkeypatch.setattr(export, "get_settings", lambda: settings(tmp_path))
    with pytest.raises(AppError) as excinfo:
        export.create_thematic_export(FakeDb([]), uuid4(), payload())
    assert excinfo.value.code == "S57_THEMATIC_NO_FEATURE"
