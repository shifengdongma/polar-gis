from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Dataset, DatasetVersion, Layer, LayerStatus, VersionStatus


def test_layer_catalog_only_lists_current_dataset_version(
    client: TestClient,
    admin_headers: dict[str, str],
    db_session: Session,
) -> None:
    admin_id = UUID(client.get("/api/v1/auth/me", headers=admin_headers).json()["id"])
    dataset = Dataset(
        code="versioned-s57",
        name="带版本海图",
        data_type="s57",
        created_by=admin_id,
    )
    db_session.add(dataset)
    db_session.flush()
    old_version = DatasetVersion(
        dataset_id=dataset.id,
        version_no=1,
        source_format="000",
        status=VersionStatus.RETIRED.value,
        content_hash="1" * 64,
    )
    current_version = DatasetVersion(
        dataset_id=dataset.id,
        version_no=2,
        source_format="001",
        status=VersionStatus.VALID.value,
        content_hash="2" * 64,
        parent_version_id=old_version.id,
    )
    db_session.add_all([old_version, current_version])
    db_session.flush()
    dataset.current_version_id = current_version.id
    db_session.add_all(
        [
            Layer(
                dataset_version_id=old_version.id,
                code="old_depth",
                name="历史等深线",
                status=LayerStatus.AVAILABLE.value,
            ),
            Layer(
                dataset_version_id=current_version.id,
                code="current_depth",
                name="当前等深线",
                status=LayerStatus.AVAILABLE.value,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/admin/layers", headers=admin_headers)

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert [item["code"] for item in response.json()["items"]] == ["current_depth"]
