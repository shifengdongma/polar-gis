from uuid import uuid4

from app.models import Project, User


def published_project(db, code):
    user = db.query(User).first()
    project = Project(
        code=code,
        name="Thematic Project",
        status="published",
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def manifest(project_id):
    return {
        "schemaVersion": "1.0",
        "exportId": "20261116T000000Z-abcd1234",
        "projectId": str(project_id),
        "name": "depth test",
        "createdAt": "2026-11-16T00:00:00+00:00",
        "crs": "EPSG:4326",
        "categories": ["depth"],
        "filters": {"objectClasses": ["SOUNDG"]},
        "bbox": None,
        "featureCount": 1,
        "complete": True,
        "truncated": False,
        "truncationReasons": [],
        "objectClasses": [],
        "classCounts": {"SOUNDG": 1},
        "cellCounts": {"NO1": 1},
        "files": [],
        "sourceDatasets": [],
        "sourceVersionIds": [],
        "sourceContentHashes": {},
        "sourceCells": ["NO1"],
        "skippedLayers": [],
        "depth": {},
        "preview": None,
        "semantics": [],
        "warnings": [],
        "stale": False,
    }


def test_thematic_catalog_api(client, db_session, user_headers, monkeypatch):
    project = published_project(db_session, f"thematic-cat-{uuid4().hex[:8]}")
    from app.api import s57_thematics as api

    monkeypatch.setattr(
        api.catalog_service,
        "build_thematic_catalog",
        lambda _db, _project_id: {},
    )
    response = client.get(
        f"/api/v1/projects/{project.id}/s57-thematics/catalog",
        headers=user_headers,
    )
    assert response.status_code == 200
    assert response.json()["classes"] == []


def test_thematic_create_and_list_api(client, db_session, user_headers, monkeypatch):
    project = published_project(db_session, f"thematic-create-{uuid4().hex[:8]}")
    from app.api import s57_thematics as api

    created = manifest(project.id)
    monkeypatch.setattr(
        api.export_service,
        "create_thematic_export",
        lambda _db, _project_id, _payload: created,
    )
    response = client.post(
        f"/api/v1/projects/{project.id}/s57-thematics/exports",
        headers=user_headers,
        json={"name": "depth test", "objectClasses": ["SOUNDG"]},
    )
    assert response.status_code == 201
    assert response.json()["exportId"] == created["exportId"]

    monkeypatch.setattr(
        api.export_service,
        "list_thematic_exports",
        lambda _project_id: ([created], []),
    )
    monkeypatch.setattr(
        api.export_service,
        "current_thematic_version_ids",
        lambda _db, _project_id: set(),
    )
    response = client.get(
        f"/api/v1/projects/{project.id}/s57-thematics/exports",
        headers=user_headers,
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["exportId"] == created["exportId"]


def test_thematic_create_rejects_empty_classes(client, db_session, user_headers):
    project = published_project(db_session, f"thematic-empty-{uuid4().hex[:8]}")
    response = client.post(
        f"/api/v1/projects/{project.id}/s57-thematics/exports",
        headers=user_headers,
        json={"name": "empty", "objectClasses": []},
    )
    assert response.status_code == 422


def test_thematic_download_single_file(client, db_session, user_headers, tmp_path, monkeypatch):
    project = published_project(db_session, f"thematic-dl-{uuid4().hex[:8]}")
    from app.api import s57_thematics as api

    data = tmp_path / "SOUNDG.geojson"
    data.write_text(
        '{"type":"FeatureCollection","features":[]}', encoding="utf-8"
    )
    current = manifest(project.id)
    current["files"] = [
        {
            "path": "depth/SOUNDG.geojson",
            "objectClass": "SOUNDG",
            "sourceCell": "NO1",
            "layerId": "layer-1",
            "featureCount": 0,
            "sha256": "a" * 64,
            "bytes": 0,
            "part": 1,
        }
    ]
    monkeypatch.setattr(
        api.export_service, "load_thematic_export", lambda _p, _e: current
    )
    monkeypatch.setattr(
        api.export_service, "thematic_file_path", lambda _p, _e, _f: data
    )
    response = client.get(
        f"/api/v1/projects/{project.id}/s57-thematics/exports/{current['exportId']}/download",
        headers=user_headers,
    )
    assert response.status_code == 200
    assert response.content.startswith(b'{"type":"FeatureCollection"')
