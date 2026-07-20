from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import datasets as datasets_api
from app.core.config import Settings
from app.models import (
    Dataset,
    DatasetVersion,
    FileAsset,
    ImportJob,
    JobStatus,
    S57ImportBatch,
    S57ImportBatchFile,
    S57ImportBatchItem,
    User,
    VersionStatus,
)
from app.services.s57_batch import S57BatchProcessor, group_s57_files, validate_s57_chain


def test_group_s57_files_by_cell_and_update() -> None:
    groups = group_s57_files(
        [
            Path("RU4AB123.000"),
            Path("RU4AB123.001"),
            Path("NO1A3000.000"),
            Path("README.docx"),
        ]
    )
    assert sorted(groups) == ["NO1A3000", "RU4AB123"]
    assert sorted(groups["RU4AB123"]) == [0, 1]


def test_reject_duplicate_cell_update() -> None:
    with pytest.raises(ValueError, match="重复更新号"):
        group_s57_files([Path("a/RU4AB123.000"), Path("b/RU4AB123.000")])


def test_reject_chain_without_base_cell() -> None:
    with pytest.raises(ValueError, match="缺少 .000"):
        validate_s57_chain("RU4AB123", {1: Path("RU4AB123.001")})


def test_reject_update_gap() -> None:
    with pytest.raises(ValueError, match=r"缺少 \.001"):
        validate_s57_chain(
            "RU4AB123",
            {0: Path("RU4AB123.000"), 2: Path("RU4AB123.002")},
        )


def test_accept_continuous_chain() -> None:
    assert validate_s57_chain(
        "RU4AB123",
        {
            0: Path("RU4AB123.000"),
            1: Path("RU4AB123.001"),
            2: Path("RU4AB123.002"),
        },
    ) == [0, 1, 2]


def test_batch_api_requires_admin(
    client: TestClient,
    user_headers: dict[str, str],
) -> None:
    response = client.post(
        "/api/v1/admin/s57-import-batches",
        headers=user_headers,
        data={"name": "无权限批次"},
        files={"files": ("RU4AB123.000", b"base", "application/octet-stream")},
    )
    assert response.status_code == 403


def test_batch_api_accepts_high_update_number_and_lists_batch(
    client: TestClient,
    admin_headers: dict[str, str],
    db_session: Session,
) -> None:
    response = client.post(
        "/api/v1/admin/s57-import-batches",
        headers=admin_headers,
        data={"name": " 高编号更新 "},
        files=[
            ("files", ("RU4AB123.000", b"base", "application/octet-stream")),
            ("files", ("RU4AB123.010", b"update", "application/octet-stream")),
        ],
    )
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "高编号更新"

    listing = client.get(
        "/api/v1/admin/s57-import-batches",
        headers=admin_headers,
        params={"page": 1, "pageSize": 10},
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["id"] == response.json()["id"]
    detail = client.get(
        f"/api/v1/admin/s57-import-batches/{response.json()['id']}",
        headers=admin_headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["items"] == []

    records = db_session.scalars(select(S57ImportBatchFile)).all()
    for record in records:
        datasets_api.storage.resolve(record.storage_key).unlink(missing_ok=True)


def test_batch_api_accepts_more_than_default_multipart_file_limit(
    client: TestClient,
    admin_headers: dict[str, str],
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved_count = 0

    async def fake_save_upload(upload: object, user_id: UUID) -> tuple[str, int, str]:
        nonlocal saved_count
        saved_count += 1
        return f"test-batch/{user_id}/{saved_count}", 1, "0" * 64

    monkeypatch.setattr(datasets_api.storage, "save_upload", fake_save_upload)
    files = [
        (
            "files",
            (f"CELL{index:04d}.000", b"x", "application/octet-stream"),
        )
        for index in range(1001)
    ]

    response = client.post(
        "/api/v1/admin/s57-import-batches",
        headers=admin_headers,
        data={"name": "超过默认文件数"},
        files=files,
    )

    assert response.status_code == 201, response.text
    assert saved_count == 1001
    assert len(db_session.scalars(select(S57ImportBatchFile)).all()) == 1001


def test_batch_api_rejects_blank_name_before_saving(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    response = client.post(
        "/api/v1/admin/s57-import-batches",
        headers=admin_headers,
        data={"name": "   "},
        files={"files": ("RU4AB123.000", b"base", "application/octet-stream")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "S57_BATCH_NAME_INVALID"


class FakeImportProcessor:
    def __init__(self, failed_cell: str | None = None) -> None:
        self.failed_cell = failed_cell
        self.calls: list[tuple[str, int]] = []

    def process(self, db: Session, job: ImportJob) -> None:
        version = db.get(DatasetVersion, job.dataset_version_id)
        assert version is not None
        cell_name = str(version.metadata_json["cellName"])
        update_number = int(version.metadata_json["updateNumber"])
        self.calls.append((cell_name, update_number))
        if cell_name == self.failed_cell:
            version.status = VersionStatus.FAILED.value
            job.status = JobStatus.FAILED.value
            job.error_code = "TEST_IMPORT_FAILED"
            job.error_message = f"{cell_name} 测试导入失败"
        else:
            dataset = db.get(Dataset, job.dataset_id)
            assert dataset is not None
            version.status = VersionStatus.VALID.value
            dataset.current_version_id = version.id
            job.status = JobStatus.SUCCEEDED.value
            job.progress = 100
        db.commit()


def create_batch(
    db: Session,
    tmp_path: Path,
    files: list[str],
) -> tuple[Settings, S57ImportBatch]:
    admin_id = db.scalar(select(User.id).where(User.username == "admin"))
    assert isinstance(admin_id, UUID)
    settings = Settings(
        storage_root=tmp_path / "storage",
        temp_root=tmp_path / "temp",
    )
    batch = S57ImportBatch(name="测试批次", requested_by=admin_id)
    db.add(batch)
    db.flush()
    for index, filename in enumerate(files):
        storage_key = f"batch-sources/{index}/{filename}"
        source = settings.storage_root / storage_key
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(filename.encode("ascii"))
        db.add(
            S57ImportBatchFile(
                batch_id=batch.id,
                original_name=filename,
                storage_key=storage_key,
                size_bytes=source.stat().st_size,
                sha256="0" * 64,
                media_type="application/octet-stream",
            )
        )
    db.commit()
    return settings, batch


def create_existing_s57_dataset(
    db: Session,
    batch: S57ImportBatch,
    cell_name: str,
    current_update: int,
) -> Dataset:
    dataset = Dataset(
        code=f"s57_{cell_name.lower()}",
        name=f"S-57 海图 {cell_name}",
        data_type="s57",
        created_by=batch.requested_by,
    )
    db.add(dataset)
    db.flush()
    parent_id: UUID | None = None
    for update_number in range(current_update + 1):
        version = DatasetVersion(
            dataset_id=dataset.id,
            version_no=update_number + 1,
            source_format=f"{update_number:03d}",
            status=VersionStatus.VALID.value,
            content_hash=str(update_number) * 64,
            parent_version_id=parent_id,
            metadata_json={"cellName": cell_name, "updateNumber": update_number},
        )
        db.add(version)
        db.flush()
        parent_id = version.id
    dataset.current_version_id = parent_id
    db.commit()
    return dataset


def test_process_batch_creates_dataset_and_jobs_for_each_cell(
    db_session: Session,
    tmp_path: Path,
) -> None:
    settings, batch = create_batch(
        db_session,
        tmp_path,
        ["RU4AB123.000", "RU4AB123.001", "NO1A3000.000"],
    )
    importer = FakeImportProcessor()
    processor = S57BatchProcessor(settings)
    processor.importer = importer  # type: ignore[assignment]

    processor.process(db_session, batch)

    db_session.refresh(batch)
    assert batch.status == JobStatus.SUCCEEDED.value
    assert (batch.total_cells, batch.succeeded_cells, batch.failed_cells) == (2, 2, 0)
    assert importer.calls == [("NO1A3000", 0), ("RU4AB123", 0), ("RU4AB123", 1)]
    assert len(db_session.scalars(select(Dataset)).all()) == 2
    assert len(db_session.scalars(select(ImportJob)).all()) == 3


def test_process_batch_reports_missing_shared_source(
    db_session: Session,
    tmp_path: Path,
) -> None:
    settings, batch = create_batch(db_session, tmp_path, ["RU4AB123.000"])
    source = settings.storage_root / "batch-sources/0/RU4AB123.000"
    source.unlink()

    S57BatchProcessor(settings).process(db_session, batch)

    db_session.refresh(batch)
    item = db_session.scalar(
        select(S57ImportBatchItem).where(S57ImportBatchItem.batch_id == batch.id)
    )
    assert batch.status == JobStatus.FAILED.value
    assert item is not None
    assert item.error_code == "S57_BATCH_SOURCE_UNAVAILABLE"
    assert "共享存储" in (item.error_message or "")


def test_process_batch_continues_after_one_cell_fails(
    db_session: Session,
    tmp_path: Path,
) -> None:
    settings, batch = create_batch(
        db_session,
        tmp_path,
        ["AA1TEST.000", "BB1TEST.000"],
    )
    processor = S57BatchProcessor(settings)
    processor.importer = FakeImportProcessor(failed_cell="AA1TEST")  # type: ignore[assignment]

    processor.process(db_session, batch)

    db_session.refresh(batch)
    items = {
        item.cell_name: item
        for item in db_session.scalars(
            select(S57ImportBatchItem).where(S57ImportBatchItem.batch_id == batch.id)
        ).all()
    }
    assert batch.status == "partial_failed"
    assert (batch.processed_cells, batch.succeeded_cells, batch.failed_cells) == (2, 1, 1)
    assert items["AA1TEST"].error_code == "TEST_IMPORT_FAILED"
    assert items["BB1TEST"].status == JobStatus.SUCCEEDED.value


def test_process_batch_reports_update_gap_without_blocking_other_cells(
    db_session: Session,
    tmp_path: Path,
) -> None:
    settings, batch = create_batch(
        db_session,
        tmp_path,
        ["AA1GAP.000", "AA1GAP.002", "BB1GOOD.000"],
    )
    processor = S57BatchProcessor(settings)
    processor.importer = FakeImportProcessor()  # type: ignore[assignment]

    processor.process(db_session, batch)

    db_session.refresh(batch)
    gap = db_session.scalar(
        select(S57ImportBatchItem).where(
            S57ImportBatchItem.batch_id == batch.id,
            S57ImportBatchItem.cell_name == "AA1GAP",
        )
    )
    assert gap is not None
    assert batch.status == "partial_failed"
    assert gap.status == JobStatus.FAILED.value
    assert gap.error_code == "S57_UPDATE_GAP"
    assert ".001" in (gap.error_message or "")
    assert db_session.scalar(select(Dataset.code).where(Dataset.code == "s57_bb1good"))


def test_process_batch_reports_duplicate_without_blocking_other_cells(
    db_session: Session,
    tmp_path: Path,
) -> None:
    settings, batch = create_batch(
        db_session,
        tmp_path,
        ["AA1DUP.000", "AA1DUP.000", "BB1GOOD.000"],
    )
    processor = S57BatchProcessor(settings)
    processor.importer = FakeImportProcessor()  # type: ignore[assignment]

    processor.process(db_session, batch)

    db_session.refresh(batch)
    duplicate = db_session.scalar(
        select(S57ImportBatchItem).where(
            S57ImportBatchItem.batch_id == batch.id,
            S57ImportBatchItem.cell_name == "AA1DUP",
        )
    )
    assert duplicate is not None
    assert batch.status == "partial_failed"
    assert duplicate.error_code == "S57_BATCH_DUPLICATE_FILE"
    assert db_session.scalar(select(Dataset.code).where(Dataset.code == "s57_bb1good"))


def test_process_batch_appends_only_new_updates_to_existing_dataset(
    db_session: Session,
    tmp_path: Path,
) -> None:
    settings, batch = create_batch(
        db_session,
        tmp_path,
        ["RU4AB123.000", "RU4AB123.001", "RU4AB123.002", "RU4AB123.003"],
    )
    dataset = create_existing_s57_dataset(db_session, batch, "RU4AB123", 1)
    processor = S57BatchProcessor(settings)
    importer = FakeImportProcessor()
    processor.importer = importer  # type: ignore[assignment]

    processor.process(db_session, batch)

    db_session.refresh(batch)
    item = db_session.scalar(
        select(S57ImportBatchItem).where(S57ImportBatchItem.batch_id == batch.id)
    )
    assert item is not None
    assert batch.status == JobStatus.SUCCEEDED.value
    assert item.dataset_id == dataset.id
    assert item.current_update == 3
    assert importer.calls == [("RU4AB123", 2), ("RU4AB123", 3)]
    versions = db_session.scalars(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset.id)
        .order_by(DatasetVersion.version_no)
    ).all()
    assert [version.source_format for version in versions] == ["000", "001", "002", "003"]
    assert len(
        db_session.scalars(
            select(FileAsset)
            .join(DatasetVersion, FileAsset.dataset_version_id == DatasetVersion.id)
            .where(DatasetVersion.dataset_id == dataset.id, FileAsset.purpose == "source")
        ).all()
    ) == 4
    assert len(db_session.scalars(select(ImportJob)).all()) == 2


def test_process_batch_marks_existing_dataset_up_to_date(
    db_session: Session,
    tmp_path: Path,
) -> None:
    settings, batch = create_batch(
        db_session,
        tmp_path,
        ["RU4AB123.000", "RU4AB123.001"],
    )
    dataset = create_existing_s57_dataset(db_session, batch, "RU4AB123", 1)
    processor = S57BatchProcessor(settings)
    processor.importer = FakeImportProcessor()  # type: ignore[assignment]

    processor.process(db_session, batch)

    item = db_session.scalar(
        select(S57ImportBatchItem).where(S57ImportBatchItem.batch_id == batch.id)
    )
    assert item is not None
    assert item.dataset_id == dataset.id
    assert item.status == JobStatus.SUCCEEDED.value
    assert item.stage == "up_to_date"
    assert item.current_update == 1
    assert not db_session.scalars(select(ImportJob)).all()


def test_process_batch_rejects_gap_when_appending_existing_dataset(
    db_session: Session,
    tmp_path: Path,
) -> None:
    settings, batch = create_batch(db_session, tmp_path, ["RU4AB123.003"])
    create_existing_s57_dataset(db_session, batch, "RU4AB123", 1)
    processor = S57BatchProcessor(settings)
    processor.importer = FakeImportProcessor()  # type: ignore[assignment]

    processor.process(db_session, batch)

    item = db_session.scalar(
        select(S57ImportBatchItem).where(S57ImportBatchItem.batch_id == batch.id)
    )
    assert item is not None
    assert item.status == JobStatus.FAILED.value
    assert item.error_code == "S57_UPDATE_GAP"
    assert ".002" in (item.error_message or "")


def test_process_batch_requires_missing_history_sources_in_reupload(
    db_session: Session,
    tmp_path: Path,
) -> None:
    settings, batch = create_batch(db_session, tmp_path, ["RU4AB123.002"])
    create_existing_s57_dataset(db_session, batch, "RU4AB123", 1)
    processor = S57BatchProcessor(settings)
    processor.importer = FakeImportProcessor()  # type: ignore[assignment]

    processor.process(db_session, batch)

    item = db_session.scalar(
        select(S57ImportBatchItem).where(S57ImportBatchItem.batch_id == batch.id)
    )
    assert item is not None
    assert item.error_code == "S57_HISTORICAL_SOURCE_MISSING"
    assert ".000" in (item.error_message or "")


def test_process_batch_rejects_existing_non_s57_dataset_code(
    db_session: Session,
    tmp_path: Path,
) -> None:
    settings, batch = create_batch(db_session, tmp_path, ["RU4AB123.000"])
    db_session.add(
        Dataset(
            code="s57_ru4ab123",
            name="已存在",
            data_type="vector",
            created_by=batch.requested_by,
        )
    )
    db_session.commit()
    processor = S57BatchProcessor(settings)
    processor.importer = FakeImportProcessor()  # type: ignore[assignment]

    processor.process(db_session, batch)

    item = db_session.scalar(
        select(S57ImportBatchItem).where(S57ImportBatchItem.batch_id == batch.id)
    )
    assert item is not None
    assert item.error_code == "DATASET_CODE_EXISTS"
