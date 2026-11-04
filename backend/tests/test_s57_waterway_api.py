from uuid import uuid4

from sqlalchemy import select

from app.models import (
    Dataset,
    DatasetVersion,
    Layer,
    Project,
    ProjectLayer,
    User,
)
from app.services.s57_waterway_catalog import classify_waterway
from app.services.s57_waterways import (
    TableMeta,
    WaterwayLayerRef,
    WaterwayResolution,
    encode_waterway_id,
    resolve_waterway_layers,
)


def published_project(db, code="test-project"):
    user = db.scalar(select(User))
    project = Project(
        code=code,
        name="Test Project",
        status="published",
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def fake_layer(**overrides):
    code = overrides.get("object_class", "FAIRWY")
    return WaterwayLayerRef(
        layer_id=overrides.get("layer_id", uuid4()),
        layer_code="s57_test_1_fairwy",
        layer_name="FAIRWY",
        dataset_id=uuid4(),
        dataset_code="s57_test",
        dataset_name="S-57 海图 TEST",
        version_no=1,
        source_cell="TEST",
        object_class=code,
        rule=classify_waterway(code),
        source_table="geo.ds_test_v1_fairwy",
        geometry_type="MultiLineString",
        fields=("objnam", "nobjnm", "inform", "rcid"),
        key_column="ogc_fid",
        key_type="int",
        geometry_column="geom",
        feature_count=3,
        available=overrides.get("available", True),
        queryable=overrides.get("queryable", True),
        renderable=True,
        reason=None,
        updated_at=None,
    )


def test_catalog_requires_auth_and_published_project(client, db_session, user_headers):
    project = published_project(db_session)
    response = client.get(f"/api/v1/projects/{project.id}/s57-waterways/catalog")
    assert response.status_code == 401

    response = client.get(
        f"/api/v1/projects/{project.id}/s57-waterways/catalog", headers=user_headers
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["classes"]
    assert payload["total"] == 0
    assert all(item["layerCount"] == 0 for item in payload["classes"])


def test_unpublished_project_is_not_visible(client, db_session, user_headers):
    user = db_session.scalar(select(User))
    project = Project(
        code="draft-project",
        name="Draft",
        status="draft",
        created_by=user.id,
        updated_by=user.id,
    )
    db_session.add(project)
    db_session.commit()
    response = client.get(
        f"/api/v1/projects/{project.id}/s57-waterways/catalog", headers=user_headers
    )
    assert response.status_code == 404


def test_search_validation_and_empty_response(client, db_session, user_headers, monkeypatch):
    project = published_project(db_session)
    from app.api import s57_waterways as api

    layer = fake_layer()
    monkeypatch.setattr(
        api.service,
        "resolve_waterway_layers",
        lambda db, project_id: WaterwayResolution(layers=(layer,), warnings=()),
    )
    monkeypatch.setattr(
        api.service, "build_waterway_search_sql", lambda layers, payload: ("", "", {})
    )
    url = f"/api/v1/projects/{project.id}/s57-waterways/search"
    response = client.post(url, headers=user_headers, json={"objectClasses": ["FAIRWY"]})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["items"] == []
    assert payload["total"] == 0

    response = client.post(url, headers=user_headers, json={"objectClasses": ["DEPARE"]})
    assert response.status_code == 422
    response = client.post(
        url, headers=user_headers, json={"objectClasses": ["FAIRWY'; DROP"]}
    )
    assert response.status_code == 422
    response = client.post(
        url,
        headers=user_headers,
        json={"objectClasses": ["FAIRWY"], "bbox": [0, 0, 200, 10]},
    )
    assert response.status_code == 422
    response = client.post(
        url, headers=user_headers, json={"objectClasses": ["FAIRWY"], "pageSize": 51}
    )
    assert response.status_code == 422


def test_detail_returns_404_for_missing_feature(client, db_session, user_headers, monkeypatch):
    project = published_project(db_session)
    from app.api import s57_waterways as api
    from app.core.errors import AppError

    def missing(db, project_id, feature_id):
        raise AppError("S57_WATERWAY_FEATURE_NOT_FOUND", "航道要素不存在", 404)

    monkeypatch.setattr(api.service, "get_waterway_feature", missing)
    response = client.get(
        f"/api/v1/projects/{project.id}/s57-waterways/{encode_waterway_id(uuid4(), '1')}",
        headers=user_headers,
    )
    assert response.status_code == 404


def test_resolve_current_version_and_field_intersection(db_session, monkeypatch):
    user = db_session.scalar(select(User))
    project = published_project(db_session, code="resolve-project")
    dataset = Dataset(
        code="s57_resolve",
        name="S-57 海图 RESOLVE",
        data_type="s57",
        created_by=user.id,
    )
    db_session.add(dataset)
    db_session.flush()
    old_version = DatasetVersion(
        dataset_id=dataset.id,
        version_no=1,
        source_format="000",
        status="retired",
        content_hash="a" * 64,
        metadata_json={"cellName": "RESOLVE"},
    )
    new_version = DatasetVersion(
        dataset_id=dataset.id,
        version_no=2,
        source_format="001",
        status="valid",
        content_hash="b" * 64,
        metadata_json={"cellName": "RESOLVE"},
    )
    db_session.add_all([old_version, new_version])
    db_session.flush()
    dataset.current_version_id = new_version.id
    old_layer = Layer(
        dataset_version_id=old_version.id,
        code="s57_resolve_1_fairwy",
        name="FAIRWY",
        geometry_type="MultiLineString",
        source_table="geo.ds_old_v1_fairwy",
        status="available",
        queryable=True,
        allowed_fields=["OBJNAM", "RCID"],
        metadata_json={"s57": {"objectClass": "FAIRWY", "featureCount": 1}},
    )
    new_layer = Layer(
        dataset_version_id=new_version.id,
        code="s57_resolve_2_tsslpt",
        name="TSSLPT",
        geometry_type="MultiLineString",
        source_table="geo.ds_new_v2_tsslpt",
        status="available",
        queryable=True,
        allowed_fields=["OBJNAM", "NOBJNM", "INFORM", "STATUS", "RCID", "OGC_FID"],
        metadata_json={"s57": {"objectClass": "TSSLPT", "featureCount": 4}},
    )
    db_session.add_all([old_layer, new_layer])
    db_session.flush()
    db_session.add_all(
        [
            ProjectLayer(project_id=project.id, layer_id=old_layer.id),
            ProjectLayer(project_id=project.id, layer_id=new_layer.id),
        ]
    )
    db_session.commit()

    def table_meta(db, tables):
        return {
            "geo.ds_new_v2_tsslpt": TableMeta(
                columns=frozenset(
                    {"ogc_fid", "objnam", "nobjnm", "inform", "status", "rcid", "geom"}
                ),
                key_column="ogc_fid",
                key_type="int",
                geometry_column="geom",
                srid=4326,
            )
        }

    monkeypatch.setattr("app.services.s57_waterways.load_table_metadata", table_meta)
    resolution = resolve_waterway_layers(db_session, project.id)
    assert [layer.object_class for layer in resolution.layers] == ["TSSLPT"]
    layer = resolution.layers[0]
    assert layer.searchable
    assert "objnam" in layer.fields
    assert "ogc_fid" not in layer.fields
    assert layer.feature_count == 4


def test_catalog_marks_unavailable_and_auxiliary(client, db_session, user_headers, monkeypatch):
    project = published_project(db_session, code="catalog-project")
    from app.api import s57_waterways as api

    available = fake_layer()
    unavailable = fake_layer(object_class="FAIRWY", available=False, queryable=False)
    aux = fake_layer(object_class="DEPARE")
    resolution = WaterwayResolution(
        layers=(available, unavailable, aux), warnings=("示例警告",)
    )
    monkeypatch.setattr(api.service, "resolve_waterway_layers", lambda db, pid: resolution)
    response = client.get(
        f"/api/v1/projects/{project.id}/s57-waterways/catalog", headers=user_headers
    )
    assert response.status_code == 200
    payload = response.json()
    classes = {item["code"]: item for item in payload["classes"]}
    assert classes["FAIRWY"]["layerCount"] == 2
    assert classes["FAIRWY"]["count"] == 6
    assert classes["FAIRWY"]["queryable"] is True
    assert classes["DEPARE"]["auxiliary"] is True
    assert payload["warnings"] == ["示例警告"]
