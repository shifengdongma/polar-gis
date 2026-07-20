from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import datasets as datasets_api
from app.models import (
    Dataset,
    DatasetType,
    DatasetVersion,
    FileAsset,
    ImportJob,
    Layer,
    LayerStatus,
    Project,
    ProjectLayer,
    ProjectStatus,
    Role,
    Upload,
    User,
)


def create_deleted_dataset(db: Session, code: str = "cleanup_test") -> Dataset:
    admin_id = db.scalar(select(User.id).where(User.role == Role.SYSTEM_ADMIN.value))
    assert isinstance(admin_id, UUID)
    dataset = Dataset(
        code=code,
        name="待清理数据集",
        data_type=DatasetType.RASTER.value,
        created_by=admin_id,
        deleted_at=datetime.now(UTC),
    )
    db.add(dataset)
    db.flush()
    version = DatasetVersion(
        dataset_id=dataset.id,
        version_no=1,
        source_format="tif",
        content_hash="a" * 64,
    )
    db.add(version)
    db.flush()
    storage_key = f"uploads/{admin_id}/{code}/source.tif"
    path = datasets_api.storage.resolve(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"source")
    db.add_all(
        [
            FileAsset(
                dataset_version_id=version.id,
                purpose="source",
                original_name="source.tif",
                storage_key=storage_key,
                size_bytes=6,
                sha256="b" * 64,
            ),
            Upload(
                original_name="source.tif",
                storage_key=storage_key,
                size_bytes=6,
                sha256="b" * 64,
                uploaded_by=admin_id,
                consumed_at=datetime.now(UTC),
            ),
            ImportJob(
                dataset_id=dataset.id,
                dataset_version_id=version.id,
                requested_by=admin_id,
            ),
            Layer(
                dataset_version_id=version.id,
                code=f"{code}_raster",
                name="待清理栅格",
                status=LayerStatus.AVAILABLE.value,
                geoserver_layer_name=f"{code}_raster",
            ),
        ]
    )
    db.commit()
    return dataset


def test_soft_delete_returns_referenced_projects(
    client: TestClient,
    admin_headers: dict[str, str],
    db_session: Session,
) -> None:
    dataset = create_deleted_dataset(db_session)
    dataset.deleted_at = None
    version = db_session.scalar(
        select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)
    )
    layer = db_session.scalar(select(Layer).where(Layer.dataset_version_id == version.id))
    admin_id = db_session.scalar(select(User.id).where(User.role == Role.SYSTEM_ADMIN.value))
    assert version and layer and isinstance(admin_id, UUID)
    project = Project(
        code="cleanup_project",
        name="引用项目",
        status=ProjectStatus.DRAFT.value,
        created_by=admin_id,
        updated_by=admin_id,
    )
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectLayer(project_id=project.id, layer_id=layer.id))
    db_session.commit()

    references = client.get(f"/api/v1/admin/datasets/{dataset.id}/references", headers=admin_headers)
    assert references.status_code == 200
    assert references.json()[0]["name"] == "引用项目"
    response = client.delete(f"/api/v1/admin/datasets/{dataset.id}", headers=admin_headers)
    assert response.status_code == 409
    assert response.json()["details"][0]["name"] == "引用项目"


def test_dataset_search_matches_name_and_code(
    client: TestClient,
    admin_headers: dict[str, str],
    db_session: Session,
) -> None:
    dataset = create_deleted_dataset(db_session, "polar_search")
    dataset.deleted_at = None
    dataset.name = "北极海图数据"
    db_session.commit()

    by_code = client.get(
        "/api/v1/admin/datasets", headers=admin_headers, params={"search": "polar_"}
    )
    by_name = client.get(
        "/api/v1/admin/datasets", headers=admin_headers, params={"search": "北极"}
    )
    assert by_code.status_code == 200
    assert by_name.status_code == 200
    assert by_code.json()["items"][0]["id"] == str(dataset.id)
    assert by_name.json()["items"][0]["id"] == str(dataset.id)


def test_bulk_delete_skips_referenced_datasets(
    client: TestClient,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
    db_session: Session,
) -> None:
    removable = create_deleted_dataset(db_session, "bulk_removable")
    referenced = create_deleted_dataset(db_session, "bulk_referenced")
    removable.deleted_at = None
    referenced.deleted_at = None
    version = db_session.scalar(
        select(DatasetVersion).where(DatasetVersion.dataset_id == referenced.id)
    )
    layer = db_session.scalar(select(Layer).where(Layer.dataset_version_id == version.id))
    admin_id = db_session.scalar(select(User.id).where(User.role == Role.SYSTEM_ADMIN.value))
    assert version and layer and isinstance(admin_id, UUID)
    project = Project(
        code="bulk_reference_project",
        name="批量删除引用项目",
        status=ProjectStatus.DRAFT.value,
        created_by=admin_id,
        updated_by=admin_id,
    )
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectLayer(project_id=project.id, layer_id=layer.id))
    db_session.commit()

    payload = {"datasetIds": [str(removable.id), str(referenced.id), str(removable.id)]}
    forbidden = client.post(
        "/api/v1/admin/datasets/bulk-delete", headers=user_headers, json=payload
    )
    assert forbidden.status_code == 403
    response = client.post(
        "/api/v1/admin/datasets/bulk-delete", headers=admin_headers, json=payload
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deletedIds"] == [str(removable.id)]
    assert body["blocked"] == [
        {
            "datasetId": str(referenced.id),
            "datasetName": referenced.name,
            "projects": [
                {
                    "id": str(project.id),
                    "code": project.code,
                    "name": project.name,
                    "status": project.status,
                }
            ],
        }
    ]
    db_session.expire_all()
    assert db_session.get(Dataset, removable.id).deleted_at is not None
    assert db_session.get(Dataset, referenced.id).deleted_at is None


def test_preview_and_purge_deleted_dataset(
    client: TestClient,
    admin_headers: dict[str, str],
    db_session: Session,
    monkeypatch,
) -> None:
    dataset = create_deleted_dataset(db_session)
    dataset_id = dataset.id
    deleted_resources: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        datasets_api.geoserver,
        "delete_layer_resource",
        lambda name, is_raster: deleted_resources.append((name, is_raster)),
    )

    preview = client.get(
        f"/api/v1/admin/datasets/{dataset.id}/cleanup-preview",
        headers=admin_headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["confirmationText"] == "DELETE cleanup_test"
    assert preview.json()["sourceFiles"]
    assert preview.json()["geoserverResources"] == ["cleanup_test_raster"]

    response = client.post(
        f"/api/v1/admin/datasets/{dataset.id}/purge",
        headers=admin_headers,
        json={"confirmation": "DELETE cleanup_test"},
    )
    assert response.status_code == 204, response.text
    assert deleted_resources == [("cleanup_test_raster", True)]
    db_session.expire_all()
    assert db_session.get(Dataset, dataset_id) is None
    assert not datasets_api.storage.resolve(preview.json()["sourceFiles"][0]).exists()


def test_preview_and_purge_multiple_deleted_datasets(
    client: TestClient,
    admin_headers: dict[str, str],
    db_session: Session,
    monkeypatch,
) -> None:
    first = create_deleted_dataset(db_session, "bulk_purge_first")
    second = create_deleted_dataset(db_session, "bulk_purge_second")
    first_id = first.id
    second_id = second.id
    first_version = db_session.scalar(
        select(DatasetVersion).where(DatasetVersion.dataset_id == first_id)
    )
    assert first_version is not None
    db_session.add(
        DatasetVersion(
            dataset_id=first_id,
            version_no=2,
            source_format="001",
            content_hash="c" * 64,
            parent_version_id=first_version.id,
        )
    )
    db_session.commit()
    deleted_resources: list[str] = []
    monkeypatch.setattr(
        datasets_api.geoserver,
        "delete_layer_resource",
        lambda name, _: deleted_resources.append(name),
    )
    payload = {"datasetIds": [str(first_id), str(second_id)]}

    preview = client.post(
        "/api/v1/admin/datasets/bulk-purge-preview",
        headers=admin_headers,
        json=payload,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["confirmationText"] == "PURGE 2 DATASETS"
    assert [item["datasetId"] for item in preview.json()["datasets"]] == [
        str(first_id),
        str(second_id),
    ]
    rejected = client.post(
        "/api/v1/admin/datasets/bulk-purge",
        headers=admin_headers,
        json={**payload, "confirmation": "PURGE 1 DATASETS"},
    )
    assert rejected.status_code == 422
    response = client.post(
        "/api/v1/admin/datasets/bulk-purge",
        headers=admin_headers,
        json={**payload, "confirmation": "PURGE 2 DATASETS"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["purgedIds"] == [str(first_id), str(second_id)]
    assert deleted_resources == ["bulk_purge_first_raster", "bulk_purge_second_raster"]
    db_session.expire_all()
    assert db_session.get(Dataset, first_id) is None
    assert db_session.get(Dataset, second_id) is None


def test_purge_rejects_incorrect_confirmation(
    client: TestClient,
    admin_headers: dict[str, str],
    db_session: Session,
) -> None:
    dataset = create_deleted_dataset(db_session)
    response = client.post(
        f"/api/v1/admin/datasets/{dataset.id}/purge",
        headers=admin_headers,
        json={"confirmation": "DELETE wrong"},
    )
    assert response.status_code == 422
    assert db_session.get(Dataset, dataset.id) is not None
