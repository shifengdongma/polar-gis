from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Dataset,
    DatasetType,
    DatasetVersion,
    Layer,
    LayerStatus,
    Project,
    ProjectLayer,
    VersionStatus,
)


def test_draft_project_is_hidden_from_regular_user(
    client: TestClient,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
) -> None:
    response = client.post(
        "/api/v1/admin/projects",
        headers=admin_headers,
        json={"code": "arctic-demo", "name": "北极演示项目", "defaultCrs": "EPSG:3413"},
    )
    assert response.status_code == 201
    projects = client.get("/api/v1/projects", headers=user_headers).json()
    assert projects["total"] == 0


def test_project_publish_requires_available_layer(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    project = client.post(
        "/api/v1/admin/projects",
        headers=admin_headers,
        json={"code": "no-layer", "name": "无图层项目"},
    ).json()
    response = client.post(
        f"/api/v1/admin/projects/{project['id']}/publish",
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "PROJECT_PUBLISH_VALIDATION_FAILED"


def test_published_project_is_visible(
    client: TestClient,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
    db_session: Session,
) -> None:
    project = client.post(
        "/api/v1/admin/projects",
        headers=admin_headers,
        json={"code": "with-layer", "name": "海图项目", "defaultCrs": "EPSG:3413"},
    ).json()
    admin_id = UUID(client.get("/api/v1/auth/me", headers=admin_headers).json()["id"])
    dataset = Dataset(
        code="demo-s57",
        name="演示S-57",
        data_type=DatasetType.S57.value,
        created_by=admin_id,
    )
    db_session.add(dataset)
    db_session.flush()
    version = DatasetVersion(
        dataset_id=dataset.id,
        version_no=1,
        source_format="000",
        status=VersionStatus.VALID.value,
        content_hash="0" * 64,
        metadata_json={"cellName": "DEMO", "updateNumber": 0},
    )
    db_session.add(version)
    db_session.flush()
    layer = Layer(
        dataset_version_id=version.id,
        code="demo_depth",
        name="等深线",
        source_table="geo.demo_depth",
        status=LayerStatus.AVAILABLE.value,
        geoserver_workspace="polar_gis",
        geoserver_layer_name="demo_depth",
        allowed_fields=["name"],
    )
    db_session.add(layer)
    dataset.current_version_id = version.id
    db_session.commit()
    response = client.put(
        f"/api/v1/admin/projects/{project['id']}/layers",
        headers=admin_headers,
        json={"layers": [{"layerId": str(layer.id), "visibleByDefault": True}]},
    )
    assert response.status_code == 200, response.text
    configured = client.get(
        f"/api/v1/admin/projects/{project['id']}/layers",
        headers=admin_headers,
    )
    assert configured.status_code == 200
    assert configured.json()[0]["layerId"] == str(layer.id)
    published = client.post(
        f"/api/v1/admin/projects/{project['id']}/publish",
        headers=admin_headers,
    )
    assert published.status_code == 200, published.text
    visible = client.get("/api/v1/projects", headers=user_headers).json()
    assert visible["total"] == 1
    config = client.get(
        f"/api/v1/projects/{project['id']}/map-config",
        headers=user_headers,
    )
    assert config.status_code == 200
    assert config.json()["datasets"][0]["id"] == str(dataset.id)
    map_layers = client.get(
        f"/api/v1/projects/{project['id']}/map-datasets/{dataset.id}/layers",
        headers=user_headers,
    )
    assert map_layers.status_code == 200
    assert map_layers.json()[0]["serviceLayerName"] == "demo_depth"
    assert map_layers.json()[0]["serviceUrl"].startswith("/geoserver/")
    legend = client.get(f"/api/v1/layers/{layer.id}/legend", headers=user_headers)
    assert legend.status_code == 200
    assert "GetLegendGraphic" in legend.json()["url"]


def test_admin_can_soft_delete_project_without_deleting_dataset(
    client: TestClient,
    admin_headers: dict[str, str],
    db_session: Session,
) -> None:
    project = client.post(
        "/api/v1/admin/projects",
        headers=admin_headers,
        json={"code": "remove-project", "name": "待删除项目"},
    ).json()
    response = client.delete(f"/api/v1/admin/projects/{project['id']}", headers=admin_headers)
    assert response.status_code == 204, response.text
    deleted = db_session.scalar(select(Project).where(Project.id == UUID(project["id"])))
    assert deleted is not None
    assert deleted.deleted_at is not None


def test_admin_can_reuse_code_after_soft_delete(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    payload = {"code": "reusable-project", "name": "项目一"}
    project = client.post("/api/v1/admin/projects", headers=admin_headers, json=payload)
    assert project.status_code == 201, project.text
    deleted = client.delete(
        f"/api/v1/admin/projects/{project.json()['id']}",
        headers=admin_headers,
    )
    assert deleted.status_code == 204, deleted.text

    recreated = client.post("/api/v1/admin/projects", headers=admin_headers, json={**payload, "name": "项目二"})
    assert recreated.status_code == 201, recreated.text


def test_dataset_layer_configuration_uses_current_version_and_expands_layers(
    client: TestClient,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
    db_session: Session,
) -> None:
    project = client.post(
        "/api/v1/admin/projects",
        headers=admin_headers,
        json={"code": "dataset-config", "name": "数据集配置项目"},
    ).json()
    admin_id = UUID(client.get("/api/v1/auth/me", headers=admin_headers).json()["id"])
    dataset = Dataset(
        code="chart-cell-01",
        name="海图单元 01",
        data_type=DatasetType.S57.value,
        created_by=admin_id,
    )
    db_session.add(dataset)
    db_session.flush()
    retired_version = DatasetVersion(
        dataset_id=dataset.id,
        version_no=1,
        source_format="000",
        status=VersionStatus.VALID.value,
        content_hash="1" * 64,
        metadata_json={},
    )
    current_version = DatasetVersion(
        dataset_id=dataset.id,
        version_no=2,
        source_format="000",
        status=VersionStatus.VALID.value,
        content_hash="2" * 64,
        metadata_json={},
    )
    db_session.add_all([retired_version, current_version])
    db_session.flush()
    db_session.add(
        Layer(
            dataset_version_id=retired_version.id,
            code="chart_cell_01_retired",
            name="历史对象",
            source_table="geo.retired",
            status=LayerStatus.AVAILABLE.value,
            allowed_fields=[],
        )
    )
    current_layers = [
        Layer(
            dataset_version_id=current_version.id,
            code=f"chart_cell_01_{name}",
            name=name,
            source_table=f"geo.{name}",
            status=LayerStatus.AVAILABLE.value,
            allowed_fields=[],
        )
        for name in ("soundg", "wrecks")
    ]
    db_session.add_all(current_layers)
    dataset.current_version_id = current_version.id
    db_session.commit()

    forbidden = client.get(
        f"/api/v1/admin/projects/{project['id']}/dataset-layers",
        headers=user_headers,
    )
    assert forbidden.status_code == 403
    catalog = client.get(
        f"/api/v1/admin/projects/{project['id']}/dataset-layers",
        headers=admin_headers,
    )
    assert catalog.status_code == 200, catalog.text
    row = catalog.json()["items"][0]
    assert catalog.json()["total"] == 1
    assert row["datasetId"] == str(dataset.id)
    assert row["versionNo"] == 2
    assert row["availableLayerCount"] == 2
    assert row["selected"] is False

    saved = client.put(
        f"/api/v1/admin/projects/{project['id']}/dataset-layers",
        headers=admin_headers,
        json={
            "datasets": [
                {
                    "datasetId": str(dataset.id),
                    "groupName": "电子海图",
                    "visibleByDefault": False,
                    "opacity": 0.8,
                }
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["layerCount"] == 1
    links = db_session.scalars(select(ProjectLayer).where(ProjectLayer.project_id == UUID(project["id"]))).all()
    assert {link.layer_id for link in links} == {layer.id for layer in current_layers}
    assert all(link.group_name == "电子海图" for link in links)
    assert all(link.style_id is None for link in links)

    configured = client.get(
        f"/api/v1/admin/projects/{project['id']}/dataset-layers",
        headers=admin_headers,
    ).json()["items"][0]
    assert configured["selected"] is True
    published = client.post(f"/api/v1/admin/projects/{project['id']}/publish", headers=admin_headers)
    assert published.status_code == 200, published.text
    map_config = client.get(
        f"/api/v1/projects/{project['id']}/map-config",
        headers=user_headers,
    ).json()
    assert len(map_config["datasets"]) == 1
    assert map_config["datasets"][0]["memberLayerCount"] == 2
    map_layers = client.get(
        f"/api/v1/projects/{project['id']}/map-datasets/{dataset.id}/layers",
        headers=user_headers,
    )
    assert {item["serviceLayerName"] for item in map_layers.json()} == {
        "chart_cell_01_soundg",
        "chart_cell_01_wrecks",
    }
