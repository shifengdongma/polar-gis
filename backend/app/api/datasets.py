import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.orm import Session, selectinload
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import require_admin
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models import (
    Dataset,
    DatasetType,
    DatasetVersion,
    FileAsset,
    ImportJob,
    JobStatus,
    Layer,
    Project,
    ProjectLayer,
    S57ImportBatch,
    S57ImportBatchFile,
    S57ImportBatchItem,
    Upload,
    User,
    VersionStatus,
)
from app.schemas import (
    DatasetBulkDeleteBlocked,
    DatasetBulkDeleteRequest,
    DatasetBulkDeleteResult,
    DatasetBulkPurgePreview,
    DatasetBulkPurgePreviewRequest,
    DatasetBulkPurgeRequest,
    DatasetBulkPurgeResult,
    DatasetCleanupPreview,
    DatasetCreate,
    DatasetProjectReferenceRead,
    DatasetPurgeRequest,
    DatasetRead,
    DatasetVersionRead,
    ImportJobRead,
    Paginated,
    S57ImportBatchDetail,
    S57ImportBatchItemRead,
    S57ImportBatchRead,
    S57UpdateCreate,
    UploadRead,
)
from app.services.audit import write_audit
from app.services.geoserver import GeoServerClient
from app.services.s57 import identify_s57_file, validate_s57_update
from app.services.storage import LocalStorage

router = APIRouter(tags=["admin-data"])
settings = get_settings()
storage = LocalStorage(settings)
geoserver = GeoServerClient(settings)
source_table_pattern = re.compile(r"^geo\.[a-z0-9_]+$")


batch_upload_openapi = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["name", "files"],
                    "properties": {
                        "name": {"type": "string", "minLength": 1, "maxLength": 180},
                        "files": {
                            "type": "array",
                            "maxItems": 5000,
                            "items": {"type": "string", "format": "binary"},
                        },
                    },
                }
            }
        },
    }
}


@router.post(
    "/admin/s57-import-batches",
    response_model=S57ImportBatchRead,
    status_code=201,
    openapi_extra=batch_upload_openapi,
)
async def create_s57_import_batch(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> S57ImportBatch:
    try:
        form = await request.form(max_files=5000, max_fields=10)
    except StarletteHTTPException as exc:
        if "Too many files" in str(exc.detail):
            raise AppError(
                "S57_BATCH_FILE_COUNT_INVALID", "请选择1至5000个文件", 422
            ) from exc
        raise AppError("S57_BATCH_FORM_INVALID", "批次上传表单无法解析", 422) from exc
    try:
        name_values = [value for key, value in form.multi_items() if key == "name"]
        file_values = [value for key, value in form.multi_items() if key == "files"]
        if len(name_values) != 1 or not isinstance(name_values[0], str):
            raise AppError("S57_BATCH_NAME_INVALID", "请输入批次名称", 422)
        if any(not isinstance(value, StarletteUploadFile) for value in file_values):
            raise AppError("S57_BATCH_FILE_INVALID", "批次文件字段无效", 422)
        return await persist_s57_import_batch(
            request,
            name_values[0],
            file_values,
            db,
            admin,
        )
    finally:
        await form.close()


async def persist_s57_import_batch(
    request: Request,
    name: str,
    files: list[StarletteUploadFile],
    db: Session,
    admin: User,
) -> S57ImportBatch:
    normalized_name = name.strip()
    if not normalized_name:
        raise AppError("S57_BATCH_NAME_INVALID", "请输入批次名称", 422)
    if not files or len(files) > 5000:
        raise AppError("S57_BATCH_FILE_COUNT_INVALID", "请选择1至5000个文件", 422)
    suffixes = [Path(file.filename or "").suffix.lower() for file in files]
    is_zip = len(files) == 1 and suffixes[0] == ".zip"
    if not is_zip and any(len(suffix) != 4 or not suffix[1:].isdigit() for suffix in suffixes):
        raise AppError("S57_BATCH_FILE_INVALID", "目录中只允许S-57三位更新号文件", 422)
    if any(suffix == ".zip" for suffix in suffixes) and not is_zip:
        raise AppError("S57_BATCH_SOURCE_MIXED", "ZIP不能与目录文件同时上传", 422)
    batch = S57ImportBatch(name=normalized_name, requested_by=admin.id)
    db.add(batch)
    db.flush()
    saved_keys: list[str] = []
    total_size = 0
    try:
        for file in files:
            storage_key, size_bytes, sha256 = await storage.save_upload(file, admin.id)
            saved_keys.append(storage_key)
            total_size += size_bytes
            if total_size > settings.max_upload_bytes:
                raise AppError("UPLOAD_TOO_LARGE", "批次文件总量超过5GB限制", 413)
            db.add(
                S57ImportBatchFile(
                    batch_id=batch.id,
                    original_name=Path(file.filename or "source").name,
                    storage_key=storage_key,
                    size_bytes=size_bytes,
                    sha256=sha256,
                    media_type=file.content_type,
                )
            )
        write_audit(
            db,
            "s57_batch.create",
            "s57_import_batch",
            "succeeded",
            user=admin,
            resource_id=str(batch.id),
            request_id=request.state.request_id,
            changes={"name": batch.name, "fileCount": len(files), "sizeBytes": total_size},
        )
        db.commit()
        db.refresh(batch)
        return batch
    except Exception:
        db.rollback()
        for storage_key in saved_keys:
            storage.resolve(storage_key).unlink(missing_ok=True)
        raise


@router.get("/admin/s57-import-batches", response_model=Paginated[S57ImportBatchRead])
def list_s57_import_batches(
    page: int = 1,
    page_size: int = 15,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Paginated[S57ImportBatchRead]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    total = db.scalar(select(func.count()).select_from(S57ImportBatch)) or 0
    items = db.scalars(
        select(S57ImportBatch)
        .order_by(S57ImportBatch.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Paginated(items=list(items), page=page, page_size=page_size, total=total)


@router.get("/admin/s57-import-batches/{batch_id}", response_model=S57ImportBatchDetail)
def get_s57_import_batch(
    batch_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> S57ImportBatchDetail:
    batch = db.get(S57ImportBatch, batch_id)
    if batch is None:
        raise AppError("S57_BATCH_NOT_FOUND", "批量导入批次不存在", 404)
    items = db.scalars(
        select(S57ImportBatchItem)
        .where(S57ImportBatchItem.batch_id == batch.id)
        .order_by(S57ImportBatchItem.cell_name)
    ).all()
    return S57ImportBatchDetail(
        **S57ImportBatchRead.model_validate(batch).model_dump(),
        items=[S57ImportBatchItemRead.model_validate(item) for item in items],
    )


@router.post(
    "/admin/s57-import-batches/{batch_id}/pause",
    response_model=S57ImportBatchRead,
)
def pause_s57_import_batch(
    batch_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> S57ImportBatch:
    batch = db.get(S57ImportBatch, batch_id)
    if batch is None:
        raise AppError("S57_BATCH_NOT_FOUND", "批量导入批次不存在", 404)
    if batch.status not in (JobStatus.RUNNING.value,):
        raise AppError(
            "S57_BATCH_CANNOT_PAUSE",
            "只能暂停正在运行中的批次",
            409,
        )
    batch.status = JobStatus.PAUSED.value
    batch.stage = "paused"
    batch.heartbeat_at = datetime.now(UTC)
    db.commit()
    db.refresh(batch)
    return batch


@router.post(
    "/admin/s57-import-batches/{batch_id}/resume",
    response_model=S57ImportBatchRead,
)
def resume_s57_import_batch(
    batch_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> S57ImportBatch:
    batch = db.get(S57ImportBatch, batch_id)
    if batch is None:
        raise AppError("S57_BATCH_NOT_FOUND", "批量导入批次不存在", 404)
    if batch.status != JobStatus.PAUSED.value:
        raise AppError(
            "S57_BATCH_CANNOT_RESUME",
            "只能恢复已暂停的批次",
            409,
        )
    batch.status = JobStatus.QUEUED.value
    batch.stage = "queued"
    batch.heartbeat_at = datetime.now(UTC)
    db.commit()
    db.refresh(batch)
    return batch


@router.post(
    "/admin/s57-import-batches/{batch_id}/cancel",
    response_model=S57ImportBatchRead,
)
def cancel_s57_import_batch(
    batch_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> S57ImportBatch:
    batch = db.get(S57ImportBatch, batch_id)
    if batch is None:
        raise AppError("S57_BATCH_NOT_FOUND", "批量导入批次不存在", 404)
    if batch.status not in (
        JobStatus.QUEUED.value,
        JobStatus.RUNNING.value,
        JobStatus.PAUSED.value,
    ):
        raise AppError(
            "S57_BATCH_CANNOT_CANCEL",
            "只能取消排队中、运行中或已暂停的批次",
            409,
        )
    batch.status = JobStatus.CANCELLED.value
    batch.stage = "cancelled"
    batch.finished_at = datetime.now(UTC)
    queued_items = db.scalars(
        select(S57ImportBatchItem).where(
            S57ImportBatchItem.batch_id == batch.id,
            S57ImportBatchItem.status.in_(
                (JobStatus.QUEUED.value, JobStatus.RUNNING.value)
            ),
        )
    ).all()
    for item in queued_items:
        item.status = JobStatus.CANCELLED.value
        item.stage = "cancelled"
        item.finished_at = datetime.now(UTC)
    db.commit()
    db.refresh(batch)
    return batch


def dataset_to_read(dataset: Dataset) -> DatasetRead:
    return DatasetRead.model_validate(dataset).model_copy(update={"version_count": len(dataset.versions)})


def dataset_or_404(db: Session, dataset_id: UUID) -> Dataset:
    dataset = db.scalar(
        select(Dataset)
        .where(Dataset.id == dataset_id, Dataset.deleted_at.is_(None))
        .options(selectinload(Dataset.versions))
    )
    if dataset is None:
        raise AppError("DATASET_NOT_FOUND", "数据集不存在", 404)
    return dataset


def dataset_project_references(db: Session, dataset_id: UUID) -> list[Project]:
    return list(
        db.scalars(
            select(Project)
            .join(ProjectLayer, ProjectLayer.project_id == Project.id)
            .join(Layer, Layer.id == ProjectLayer.layer_id)
            .join(DatasetVersion, DatasetVersion.id == Layer.dataset_version_id)
            .where(DatasetVersion.dataset_id == dataset_id, Project.deleted_at.is_(None))
            .distinct()
            .order_by(Project.name)
        ).all()
    )


def soft_delete_dataset(
    db: Session,
    dataset: Dataset,
    request: Request,
    admin: User,
) -> None:
    dataset.deleted_at = datetime.now(UTC)
    write_audit(
        db,
        "dataset.delete",
        "dataset",
        "succeeded",
        user=admin,
        resource_id=str(dataset.id),
        request_id=request.state.request_id,
        changes={"physicalCleanupRequired": True},
    )


def cleanup_preview(db: Session, dataset: Dataset) -> DatasetCleanupPreview:
    versions = list(
        db.scalars(select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)).all()
    )
    version_ids = [version.id for version in versions]
    files = list(
        db.scalars(select(FileAsset).where(FileAsset.dataset_version_id.in_(version_ids))).all()
    ) if version_ids else []
    layers = list(
        db.scalars(select(Layer).where(Layer.dataset_version_id.in_(version_ids))).all()
    ) if version_ids else []
    return DatasetCleanupPreview(
        dataset_id=dataset.id,
        dataset_code=dataset.code,
        dataset_name=dataset.name,
        deleted_at=dataset.deleted_at or dataset.updated_at,
        confirmation_text=f"DELETE {dataset.code}",
        source_files=[file.storage_key for file in files],
        derived_tables=sorted({layer.source_table for layer in layers if layer.source_table}),
        geoserver_resources=sorted(
            {layer.geoserver_layer_name or layer.code for layer in layers}
        ),
        version_count=len(versions),
        layer_count=len(layers),
    )


def purgeable_datasets(db: Session, dataset_ids: list[UUID]) -> list[Dataset]:
    unique_ids = list(dict.fromkeys(dataset_ids))
    datasets = {dataset.id: dataset for dataset in db.scalars(select(Dataset).where(Dataset.id.in_(unique_ids))).all()}
    unavailable: list[dict[str, str]] = []
    for dataset_id in unique_ids:
        dataset = datasets.get(dataset_id)
        if dataset is None or dataset.deleted_at is None:
            unavailable.append({"id": str(dataset_id), "reason": "数据集不存在或尚未软删除"})
        elif dataset_project_references(db, dataset.id):
            unavailable.append({"id": str(dataset.id), "reason": "数据集仍被项目引用"})
    if unavailable:
        raise AppError("DATASET_PURGE_UNAVAILABLE", "存在不能永久清理的数据集", 409, unavailable)
    return [datasets[dataset_id] for dataset_id in unique_ids]


def purge_dataset_resources(
    db: Session,
    dataset: Dataset,
    preview: DatasetCleanupPreview,
    request: Request,
    admin: User,
) -> None:
    versions = list(db.scalars(select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)).all())
    version_ids = [version.id for version in versions]
    files = list(db.scalars(select(FileAsset).where(FileAsset.dataset_version_id.in_(version_ids))).all()) if version_ids else []
    layers = list(db.scalars(select(Layer).where(Layer.dataset_version_id.in_(version_ids))).all()) if version_ids else []
    for table_name in {layer.source_table for layer in layers if layer.source_table}:
        if not source_table_pattern.fullmatch(table_name):
            raise AppError("DATASET_CLEANUP_SOURCE_INVALID", "派生表名称无效", 500)
    for layer in layers:
        geoserver.delete_layer_resource(layer.geoserver_layer_name or layer.code, dataset.data_type == DatasetType.RASTER.value)
    for table_name in {layer.source_table for layer in layers if layer.source_table}:
        if db.bind and db.bind.dialect.name == "postgresql":
            db.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
    for file in files:
        storage.delete(file.storage_key)
    if version_ids:
        storage_keys = [file.storage_key for file in files]
        if storage_keys:
            db.execute(delete(Upload).where(Upload.storage_key.in_(storage_keys)))
        db.execute(update(S57ImportBatchItem).where(S57ImportBatchItem.dataset_id == dataset.id).values(dataset_id=None))
        db.execute(delete(ImportJob).where(ImportJob.dataset_id == dataset.id))
        db.execute(delete(ProjectLayer).where(ProjectLayer.layer_id.in_([layer.id for layer in layers])))
        db.execute(delete(Layer).where(Layer.dataset_version_id.in_(version_ids)))
        db.execute(delete(FileAsset).where(FileAsset.dataset_version_id.in_(version_ids)))
        db.execute(
            update(DatasetVersion)
            .where(DatasetVersion.parent_version_id.in_(version_ids))
            .values(parent_version_id=None)
        )
        db.execute(delete(DatasetVersion).where(DatasetVersion.id.in_(version_ids)))
    db.delete(dataset)
    write_audit(
        db,
        "dataset.purge",
        "dataset",
        "succeeded",
        user=admin,
        resource_id=str(dataset.id),
        request_id=request.state.request_id,
        changes={
            "sourceFileCount": len(files),
            "derivedTableCount": len(preview.derived_tables),
            "geoserverResourceCount": len(preview.geoserver_resources),
        },
    )


@router.post("/admin/uploads", response_model=UploadRead, status_code=201)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> Upload:
    storage_key, size_bytes, sha256 = await storage.save_upload(file, admin.id)
    upload = Upload(
        original_name=Path(file.filename or "upload.bin").name,
        storage_key=storage_key,
        size_bytes=size_bytes,
        sha256=sha256,
        media_type=file.content_type,
        uploaded_by=admin.id,
    )
    db.add(upload)
    db.flush()
    write_audit(
        db,
        "upload.create",
        "upload",
        "succeeded",
        user=admin,
        resource_id=str(upload.id),
        request_id=request.state.request_id,
        changes={"fileName": upload.original_name, "sizeBytes": upload.size_bytes},
    )
    db.commit()
    db.refresh(upload)
    return upload


@router.get("/admin/uploads/{upload_id}", response_model=UploadRead)
def get_upload(
    upload_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Upload:
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise AppError("UPLOAD_NOT_FOUND", "上传记录不存在", 404)
    return upload


@router.delete("/admin/uploads/{upload_id}", status_code=204)
def delete_upload(
    upload_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise AppError("UPLOAD_NOT_FOUND", "上传记录不存在", 404)
    if upload.consumed_at is not None:
        raise AppError("UPLOAD_ALREADY_CONSUMED", "上传已用于数据集，不能删除", 409)
    path = storage.resolve(upload.storage_key)
    path.unlink(missing_ok=True)
    db.delete(upload)
    db.commit()


@router.get("/admin/datasets", response_model=Paginated[DatasetRead])
def list_datasets(
    page: int = 1,
    page_size: int = 15,
    search: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Paginated[DatasetRead]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    conditions = [Dataset.deleted_at.is_(None)]
    if search:
        keyword = f"%{search.strip()}%"
        if search.strip():
            conditions.append(or_(Dataset.name.ilike(keyword), Dataset.code.ilike(keyword)))
    total = db.scalar(select(func.count()).select_from(Dataset).where(*conditions)) or 0
    datasets = db.scalars(
        select(Dataset)
        .where(*conditions)
        .options(selectinload(Dataset.versions))
        .order_by(Dataset.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Paginated(
        items=[dataset_to_read(item) for item in datasets],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/admin/datasets/available-ids")
def get_available_dataset_ids(
    search: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[dict]:
    conditions = [
        Dataset.deleted_at.is_(None),
        Dataset.current_version_id.is_not(None),
    ]
    if search and search.strip():
        keyword = f"%{search.strip()}%"
        conditions.append(
            or_(Dataset.name.ilike(keyword), Dataset.code.ilike(keyword))
        )
    rows = db.execute(
        select(Dataset.id, Dataset.code, Dataset.name)
        .where(*conditions)
        .order_by(Dataset.name)
    ).all()
    return [
        {"datasetId": str(row.id), "code": row.code, "name": row.name}
        for row in rows
    ]


@router.post("/admin/datasets", response_model=DatasetRead, status_code=201)
def create_dataset(
    payload: DatasetCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> DatasetRead:
    if db.scalar(select(Dataset).where(Dataset.code == payload.code)):
        raise AppError("DATASET_CODE_EXISTS", "数据集代码已存在", 409)
    upload = db.get(Upload, payload.upload_id)
    if upload is None or upload.consumed_at is not None:
        raise AppError("UPLOAD_NOT_AVAILABLE", "上传不存在或已被使用", 409)
    suffix = Path(upload.original_name).suffix.lower()
    if payload.data_type == DatasetType.S57 and not suffix[1:].isdigit():
        raise AppError("S57_FILENAME_INVALID", "S-57文件扩展名必须为三位更新号", 422)
    dataset = Dataset(
        code=payload.code,
        name=payload.name,
        data_type=payload.data_type.value,
        description=payload.description,
        created_by=admin.id,
    )
    db.add(dataset)
    db.flush()
    version = DatasetVersion(
        dataset_id=dataset.id,
        version_no=1,
        source_format=suffix.lstrip("."),
        source_crs=payload.source_crs,
        status=VersionStatus.PROCESSING.value,
        content_hash=upload.sha256,
        metadata_json={},
    )
    db.add(version)
    db.flush()
    db.add(
        FileAsset(
            dataset_version_id=version.id,
            purpose="source",
            original_name=upload.original_name,
            storage_key=upload.storage_key,
            size_bytes=upload.size_bytes,
            sha256=upload.sha256,
            media_type=upload.media_type,
        )
    )
    job = ImportJob(
        dataset_id=dataset.id,
        dataset_version_id=version.id,
        job_type="initial_import",
        requested_by=admin.id,
    )
    db.add(job)
    upload.consumed_at = datetime.now(UTC)
    write_audit(
        db,
        "dataset.create",
        "dataset",
        "succeeded",
        user=admin,
        resource_id=str(dataset.id),
        request_id=request.state.request_id,
        changes={"dataType": dataset.data_type, "jobId": str(job.id)},
    )
    db.commit()
    return dataset_to_read(dataset_or_404(db, dataset.id))


@router.get("/admin/datasets/deleted", response_model=list[DatasetCleanupPreview])
def list_deleted_datasets(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[DatasetCleanupPreview]:
    datasets = db.scalars(
        select(Dataset)
        .where(Dataset.deleted_at.is_not(None))
        .order_by(Dataset.deleted_at.desc())
    ).all()
    return [cleanup_preview(db, dataset) for dataset in datasets]


@router.post("/admin/datasets/bulk-delete", response_model=DatasetBulkDeleteResult)
def bulk_delete_datasets(
    payload: DatasetBulkDeleteRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> DatasetBulkDeleteResult:
    dataset_ids = list(dict.fromkeys(payload.dataset_ids))
    datasets = {
        dataset.id: dataset
        for dataset in db.scalars(
            select(Dataset).where(
                Dataset.id.in_(dataset_ids), Dataset.deleted_at.is_(None)
            )
        ).all()
    }
    deleted_ids: list[UUID] = []
    blocked: list[DatasetBulkDeleteBlocked] = []
    for dataset_id in dataset_ids:
        dataset = datasets.get(dataset_id)
        if dataset is None:
            continue
        references = dataset_project_references(db, dataset.id)
        if references:
            blocked.append(
                DatasetBulkDeleteBlocked(
                    dataset_id=dataset.id,
                    dataset_name=dataset.name,
                    projects=[DatasetProjectReferenceRead.model_validate(project) for project in references],
                )
            )
            continue
        soft_delete_dataset(db, dataset, request, admin)
        deleted_ids.append(dataset.id)
    db.commit()
    return DatasetBulkDeleteResult(deleted_ids=deleted_ids, blocked=blocked)


@router.get(
    "/admin/datasets/{dataset_id}/references",
    response_model=list[DatasetProjectReferenceRead],
)
def get_dataset_references(
    dataset_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[Project]:
    dataset_or_404(db, dataset_id)
    return dataset_project_references(db, dataset_id)


@router.get(
    "/admin/datasets/{dataset_id}/cleanup-preview",
    response_model=DatasetCleanupPreview,
)
def get_dataset_cleanup_preview(
    dataset_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> DatasetCleanupPreview:
    dataset = purgeable_datasets(db, [dataset_id])[0]
    return cleanup_preview(db, dataset)


@router.post("/admin/datasets/bulk-purge-preview", response_model=DatasetBulkPurgePreview)
def preview_bulk_purge_datasets(
    payload: DatasetBulkPurgePreviewRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> DatasetBulkPurgePreview:
    datasets = purgeable_datasets(db, payload.dataset_ids)
    return DatasetBulkPurgePreview(
        confirmation_text=f"PURGE {len(datasets)} DATASETS",
        datasets=[cleanup_preview(db, dataset) for dataset in datasets],
    )


@router.post("/admin/datasets/bulk-purge", response_model=DatasetBulkPurgeResult)
def bulk_purge_datasets(
    payload: DatasetBulkPurgeRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> DatasetBulkPurgeResult:
    datasets = purgeable_datasets(db, payload.dataset_ids)
    confirmation_text = f"PURGE {len(datasets)} DATASETS"
    if payload.confirmation != confirmation_text:
        raise AppError("DATASET_PURGE_CONFIRMATION_INVALID", "确认文本不匹配", 422)
    previews = [cleanup_preview(db, dataset) for dataset in datasets]
    purged_ids: list[UUID] = []
    for dataset, preview in zip(datasets, previews, strict=True):
        dataset_id = dataset.id
        try:
            purge_dataset_resources(db, dataset, preview, request, admin)
            # Large S-57 batches may own thousands of derived tables. Commit each
            # prevalidated dataset so PostgreSQL can release DDL locks promptly.
            db.commit()
            purged_ids.append(dataset_id)
        except Exception as exc:
            db.rollback()
            raise AppError(
                "DATASET_BULK_PURGE_PARTIAL",
                "批量清理未能全部完成，请刷新后查看剩余数据集",
                409,
                {"purgedIds": [str(item) for item in purged_ids], "failedDatasetId": str(dataset_id)},
            ) from exc
    return DatasetBulkPurgeResult(purged_ids=purged_ids)


@router.post("/admin/datasets/{dataset_id}/purge", status_code=204)
def purge_dataset(
    dataset_id: UUID,
    payload: DatasetPurgeRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> None:
    dataset = purgeable_datasets(db, [dataset_id])[0]
    preview = cleanup_preview(db, dataset)
    if payload.confirmation != preview.confirmation_text:
        raise AppError("DATASET_PURGE_CONFIRMATION_INVALID", "确认文本不匹配", 422)
    purge_dataset_resources(db, dataset, preview, request, admin)
    db.commit()


@router.get("/admin/datasets/{dataset_id}", response_model=DatasetRead)
def get_dataset(
    dataset_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> DatasetRead:
    return dataset_to_read(dataset_or_404(db, dataset_id))


@router.get("/admin/datasets/{dataset_id}/versions", response_model=list[DatasetVersionRead])
def get_dataset_versions(
    dataset_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[DatasetVersion]:
    dataset_or_404(db, dataset_id)
    return list(
        db.scalars(
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset_id)
            .order_by(DatasetVersion.version_no.desc())
        ).all()
    )


@router.post("/admin/datasets/{dataset_id}/s57-updates", response_model=ImportJobRead, status_code=201)
def create_s57_update(
    dataset_id: UUID,
    payload: S57UpdateCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ImportJob:
    dataset = dataset_or_404(db, dataset_id)
    if dataset.data_type != DatasetType.S57.value or dataset.current_version_id is None:
        raise AppError("S57_DATASET_REQUIRED", "当前数据集不是有效S-57数据集", 422)
    current = db.get(DatasetVersion, dataset.current_version_id)
    upload = db.get(Upload, payload.upload_id)
    if current is None or upload is None or upload.consumed_at is not None:
        raise AppError("UPLOAD_NOT_AVAILABLE", "上传不存在或已被使用", 409)
    identity = identify_s57_file(Path(upload.original_name))
    expected_cell = str(current.metadata_json.get("cellName", ""))
    current_update = int(current.metadata_json.get("updateNumber", 0))
    validate_s57_update(identity, expected_cell, current_update)
    next_version_no = max(version.version_no for version in dataset.versions) + 1
    version = DatasetVersion(
        dataset_id=dataset.id,
        version_no=next_version_no,
        source_format=f"{identity.update_number:03d}",
        source_crs=current.source_crs,
        status=VersionStatus.PROCESSING.value,
        content_hash=upload.sha256,
        parent_version_id=current.id,
        metadata_json={"cellName": identity.cell_name, "updateNumber": identity.update_number},
    )
    db.add(version)
    db.flush()
    db.add(
        FileAsset(
            dataset_version_id=version.id,
            purpose="source",
            original_name=upload.original_name,
            storage_key=upload.storage_key,
            size_bytes=upload.size_bytes,
            sha256=upload.sha256,
            media_type=upload.media_type,
        )
    )
    job = ImportJob(
        dataset_id=dataset.id,
        dataset_version_id=version.id,
        job_type="s57_update",
        requested_by=admin.id,
    )
    db.add(job)
    upload.consumed_at = datetime.now(UTC)
    write_audit(
        db,
        "dataset.s57_update",
        "dataset",
        "succeeded",
        user=admin,
        resource_id=str(dataset.id),
        request_id=request.state.request_id,
        changes={"updateNumber": identity.update_number, "jobId": str(job.id)},
    )
    db.commit()
    db.refresh(job)
    return job


@router.post("/admin/datasets/{dataset_id}/rollback", response_model=DatasetRead)
def rollback_dataset(
    dataset_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> DatasetRead:
    dataset = dataset_or_404(db, dataset_id)
    if dataset.current_version_id is None:
        raise AppError("DATASET_ROLLBACK_UNAVAILABLE", "没有可回退的当前版本", 409)
    current = db.get(DatasetVersion, dataset.current_version_id)
    if current is None or current.parent_version_id is None:
        raise AppError("DATASET_ROLLBACK_UNAVAILABLE", "没有上一有效版本", 409)
    parent = db.get(DatasetVersion, current.parent_version_id)
    if parent is None or parent.status not in {VersionStatus.VALID.value, VersionStatus.RETIRED.value}:
        raise AppError("DATASET_ROLLBACK_UNAVAILABLE", "上一版本不可用", 409)
    current_layers = db.scalars(
        select(Layer).where(Layer.dataset_version_id == current.id)
    ).all()
    parent_layers = db.scalars(
        select(Layer).where(Layer.dataset_version_id == parent.id)
    ).all()
    parent_by_source = {
        layer.metadata_json.get("sourceLayer", "raster"): layer for layer in parent_layers
    }
    for current_layer in current_layers:
        replacement = parent_by_source.get(current_layer.metadata_json.get("sourceLayer", "raster"))
        if replacement is None:
            continue
        links = db.scalars(
            select(ProjectLayer).where(ProjectLayer.layer_id == current_layer.id)
        ).all()
        for link in links:
            link.layer_id = replacement.id
    current.status = VersionStatus.RETIRED.value
    parent.status = VersionStatus.VALID.value
    dataset.current_version_id = parent.id
    write_audit(
        db,
        "dataset.rollback",
        "dataset",
        "succeeded",
        user=admin,
        resource_id=str(dataset.id),
        request_id=request.state.request_id,
        changes={"fromVersion": current.version_no, "toVersion": parent.version_no},
    )
    db.commit()
    return dataset_to_read(dataset_or_404(db, dataset.id))


@router.delete("/admin/datasets/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> None:
    dataset = dataset_or_404(db, dataset_id)
    references = dataset_project_references(db, dataset.id)
    if references:
        raise AppError(
            "DATASET_IN_USE",
            "数据集仍被项目引用",
            409,
            [{"id": str(project.id), "code": project.code, "name": project.name} for project in references],
        )
    soft_delete_dataset(db, dataset, request, admin)
    db.commit()


@router.get("/admin/import-jobs", response_model=Paginated[ImportJobRead])
def list_import_jobs(
    page: int = 1,
    page_size: int = 15,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Paginated[ImportJobRead]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    total = db.scalar(select(func.count()).select_from(ImportJob)) or 0
    jobs = db.scalars(
        select(ImportJob)
        .order_by(ImportJob.queued_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Paginated(items=list(jobs), page=page, page_size=page_size, total=total)


@router.get("/admin/import-jobs/{job_id}", response_model=ImportJobRead)
def get_import_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if job is None:
        raise AppError("IMPORT_JOB_NOT_FOUND", "导入任务不存在", 404)
    return job


@router.post("/admin/import-jobs/{job_id}/retry", response_model=ImportJobRead)
def retry_import_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if job is None:
        raise AppError("IMPORT_JOB_NOT_FOUND", "导入任务不存在", 404)
    if job.status != JobStatus.FAILED.value:
        raise AppError("IMPORT_JOB_CONFLICT", "只有失败任务可以重试", 409)
    job.status = JobStatus.QUEUED.value
    job.stage = "queued"
    job.progress = 0
    job.error_code = None
    job.error_message = None
    job.started_at = None
    job.finished_at = None
    db.commit()
    db.refresh(job)
    return job


@router.post("/admin/import-jobs/{job_id}/cancel", response_model=ImportJobRead)
def cancel_import_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if job is None:
        raise AppError("IMPORT_JOB_NOT_FOUND", "导入任务不存在", 404)
    if job.status not in {JobStatus.QUEUED.value, JobStatus.RUNNING.value}:
        raise AppError("IMPORT_JOB_CONFLICT", "当前任务不能取消", 409)
    job.status = JobStatus.CANCELLED.value
    job.stage = "cancelled"
    job.finished_at = datetime.now(UTC)
    db.commit()
    db.refresh(job)
    return job
