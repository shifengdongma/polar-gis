"""API endpoints for S-57 basemap import operations.

All endpoints require system_admin role.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models import (
    JobStatus,
    S57ImportBatch,
    S57ImportBatchFile,
    S57ImportBatchItem,
    Upload,
    User,
)
from app.schemas import ApiModel, S57ImportBatchDetail, S57ImportBatchItemRead, S57ImportBatchRead
from app.services.s57_basemap import (
    ERR_IMPORT_ALREADY_RUNNING,
    ERR_MANIFEST_CHANGED,
    ERR_PROFILE_NOT_FOUND,
    ERR_SOURCE_NOT_CONFIGURED,
    BasemapPreflightService,
    PreflightResult,
    list_available_profiles,
    load_profile,
)
from app.services.storage import LocalStorage

logger = logging.getLogger("polar_gis.api.s57_basemaps")

router = APIRouter(prefix="/admin/s57-basemaps", tags=["admin-s57-basemaps"])


# ── request / response schemas ───────────────────────────────────────

class PreflightRequest(ApiModel):
    profile_code: str = Field(default="global_overview_v1", min_length=1, max_length=64)
    source_type: str = Field(default="server_directory", pattern=r"^(server_directory|upload)$")
    upload_id: UUID | None = None


class ImportRequest(ApiModel):
    profile_code: str = Field(default="global_overview_v1", min_length=1, max_length=64)
    manifest_hash: str = Field(min_length=1, max_length=256)
    source_type: str = Field(default="server_directory", pattern=r"^(server_directory|upload)$")
    upload_id: UUID | None = None
    set_as_default: bool = False
    build_wmts_3857: bool = True
    build_wmts_3413: bool = True
    warm_low_zoom_cache: bool = False


class ProfileRead(ApiModel):
    code: str
    name: str
    usage_band: int
    cell_count: int
    file_count: int
    description: str


class PreflightResponse(ApiModel):
    profile_code: str
    profile_name: str
    manifest_hash: str
    expected_cell_count: int
    expected_file_count: int
    discovered_cell_count: int
    selected_file_count: int
    ignored_file_count: int
    create_cell_count: int
    update_cell_count: int
    skip_cell_count: int
    blocked_cell_count: int
    total_size_bytes: int
    coverage_extent: list[float]
    coverage_verified: bool
    coverage_message: str
    can_start: bool
    cells: list[dict]
    ignored_files: list[str]


class ImportResponse(ApiModel):
    batch_id: UUID
    profile_code: str
    status: str
    selected_cell_count: int
    selected_file_count: int


class BasemapRunDetail(S57ImportBatchDetail):
    post_process_status: str | None = None
    layer_group_status: str | None = None
    wmts_3857_status: str | None = None
    wmts_3413_status: str | None = None
    cache_warm_status: str | None = None
    base_map_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ── helpers ──────────────────────────────────────────────────────────

def _preflight_to_response(r: PreflightResult) -> PreflightResponse:
    return PreflightResponse(
        profile_code=r.profile_code,
        profile_name=r.profile_name,
        manifest_hash=r.manifest_hash,
        expected_cell_count=r.expected_cell_count,
        expected_file_count=r.expected_file_count,
        discovered_cell_count=r.discovered_cell_count,
        selected_file_count=r.selected_file_count,
        ignored_file_count=r.ignored_file_count,
        create_cell_count=r.create_cell_count,
        update_cell_count=r.update_cell_count,
        skip_cell_count=r.skip_cell_count,
        blocked_cell_count=r.blocked_cell_count,
        total_size_bytes=r.total_size_bytes,
        coverage_extent=r.coverage_extent,
        coverage_verified=r.coverage_verified,
        coverage_message=r.coverage_message,
        can_start=r.can_start,
        cells=r.cells,
        ignored_files=r.ignored_files[:100],
    )


def _enrich_batch_detail(detail: S57ImportBatchDetail) -> BasemapRunDetail:
    meta = detail.metadata_json.get("basemap", {}) if detail.metadata_json else {}
    return BasemapRunDetail(
        id=detail.id,
        name=detail.name,
        status=detail.status,
        stage=detail.stage,
        progress=detail.progress,
        total_cells=detail.total_cells,
        processed_cells=detail.processed_cells,
        succeeded_cells=detail.succeeded_cells,
        failed_cells=detail.failed_cells,
        purpose=detail.purpose,
        metadata_json=detail.metadata_json,
        created_at=detail.created_at,
        started_at=detail.started_at,
        finished_at=detail.finished_at,
        items=detail.items,
        post_process_status=meta.get("postProcessStatus"),
        layer_group_status=meta.get("layerGroupStatus"),
        wmts_3857_status=meta.get("wmts3857Status"),
        wmts_3413_status=meta.get("wmts3413Status"),
        cache_warm_status=meta.get("cacheWarmStatus"),
        base_map_ids=meta.get("baseMapIds", []),
        warnings=meta.get("warnings", []),
    )


# ── endpoints ────────────────────────────────────────────────────────

@router.get("/profiles", response_model=list[ProfileRead])
def get_profiles(
    _user: User = Depends(require_admin),
) -> list[ProfileRead]:
    """List available basemap profiles."""
    profiles = list_available_profiles()
    return [
        ProfileRead(
            code=p.code,
            name=p.name,
            usage_band=p.usage_band,
            cell_count=len(p.expected_cells),
            file_count=sum(p.expected_cells.values()) + len(p.expected_cells),
            description=p.description,
        )
        for p in profiles
    ]


@router.post("/preflight", response_model=PreflightResponse)
def run_preflight(
    body: PreflightRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> PreflightResponse:
    """Validate source data against a basemap profile."""
    settings = get_settings()
    service = BasemapPreflightService(settings)

    try:
        _ = load_profile(body.profile_code)
    except FileNotFoundError:
        raise AppError(
            code=ERR_PROFILE_NOT_FOUND,
            message=f"底图 profile 未找到: {body.profile_code}",
            status_code=404,
        )

    upload_dir = None
    if body.source_type == "upload" and body.upload_id:
        storage = LocalStorage(settings)
        upload = db.get(Upload, body.upload_id)
        if upload is None:
            raise AppError(
                code="UPLOAD_NOT_FOUND",
                message="上传文件未找到",
                status_code=404,
            )
        upload_dir = storage.resolve(upload.storage_key).parent

    if body.source_type == "server_directory" and not settings.s57_basemap_allow_local_source:
        raise AppError(
            code=ERR_SOURCE_NOT_CONFIGURED,
            message="服务器目录数据源未启用",
            status_code=400,
        )

    result = service.preflight(db, body.profile_code, body.source_type, upload_dir)
    return _preflight_to_response(result)


@router.post("/import", response_model=ImportResponse)
def start_basemap_import(
    body: ImportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> ImportResponse:
    """Start a one-click basemap import after successful preflight."""
    settings = get_settings()
    service = BasemapPreflightService(settings)

    # re-validate manifest
    try:
        profile = load_profile(body.profile_code)
    except FileNotFoundError:
        raise AppError(
            code=ERR_PROFILE_NOT_FOUND,
            message=f"底图 profile 未找到: {body.profile_code}",
            status_code=404,
        )

    # check for existing running import of same profile
    existing = db.scalars(
        select(S57ImportBatch).where(
            S57ImportBatch.purpose == "basemap",
            S57ImportBatch.status.in_(
                (JobStatus.QUEUED.value, JobStatus.RUNNING.value, JobStatus.PAUSED.value)
            ),
        )
    ).first()
    if existing is not None:
        raise AppError(
            code=ERR_IMPORT_ALREADY_RUNNING,
            message="同一 profile 已有运行中的导入",
            status_code=409,
            details={"existingBatchId": str(existing.id)},
        )

    # re-run preflight to validate manifest
    upload_dir = None
    if body.source_type == "upload" and body.upload_id:
        upload = db.get(Upload, body.upload_id)
        if upload:
            storage = LocalStorage(settings)
            upload_dir = storage.resolve(upload.storage_key).parent

    result = service.preflight(db, body.profile_code, body.source_type, upload_dir)
    if result.manifest_hash != body.manifest_hash:
        raise AppError(
            code=ERR_MANIFEST_CHANGED,
            message="数据包 manifest 已变化，请重新预检",
            status_code=409,
            details={"newManifestHash": result.manifest_hash},
        )

    if not result.can_start:
        raise AppError(
            code="BASEMAP_CANNOT_START",
            message=f"预检未通过，{result.blocked_cell_count} 个 Cell 被阻塞",
            status_code=400,
        )

    # create batch
    now = datetime.now(UTC)
    batch_name = f"{profile.name} {now.strftime('%Y-%m-%d %H:%M')}"

    batch = S57ImportBatch(
        name=batch_name,
        status=JobStatus.QUEUED.value,
        purpose="basemap",
        total_cells=result.selected_file_count,  # rough
        requested_by=user.id,
        metadata_json={
            "basemap": {
                "profileCode": result.profile_code,
                "manifestHash": result.manifest_hash,
                "sourceType": body.source_type,
                "postProcessStatus": "pending",
                "layerGroupName": None,
                "wmts3857BaseMapId": None,
                "wmts3413BaseMapId": None,
                "coverageExtent": result.coverage_extent,
                "warnings": [],
            }
        },
    )
    db.add(batch)
    db.flush()

    # create batch file records for each selected file
    source_root = Path(settings.s57_basemap_source_root) if body.source_type == "server_directory" else upload_dir
    for cell_data in result.cells:
        if cell_data.get("action") == "blocked":
            continue
        cell_name = cell_data["cellName"]
        for upd in cell_data.get("discoveredUpdates", []):
            fname = f"{cell_name}.{upd:03d}"
            fpath = source_root / fname if source_root else None
            if fpath and fpath.is_file():
                bf = S57ImportBatchFile(
                    batch_id=batch.id,
                    original_name=fname,
                    storage_key=str(fpath),
                    size_bytes=fpath.stat().st_size,
                    sha256="",  # will be recomputed by worker
                )
                db.add(bf)

    # create batch items for each expected cell
    for cell_data in result.cells:
        item = S57ImportBatchItem(
            batch_id=batch.id,
            cell_name=cell_data["cellName"],
            status=JobStatus.QUEUED.value,
            update_count=len(cell_data.get("discoveredUpdates", [])),
            current_update=cell_data.get("expectedMaxUpdate", 0),
        )
        db.add(item)

    db.commit()

    return ImportResponse(
        batch_id=batch.id,
        profile_code=result.profile_code,
        status="queued",
        selected_cell_count=result.expected_cell_count,
        selected_file_count=result.selected_file_count,
    )


@router.get("/runs/{batch_id}", response_model=BasemapRunDetail)
def get_basemap_run(
    batch_id: UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> BasemapRunDetail:
    """Get detailed status of a basemap import run."""
    batch = db.get(S57ImportBatch, batch_id)
    if batch is None:
        raise AppError(
            code="BATCH_NOT_FOUND",
            message="批次未找到",
            status_code=404,
        )

    from app.schemas import S57ImportBatchDetail, S57ImportBatchItemRead
    from app.models import S57ImportBatchItem as ItemModel

    items = db.scalars(
        select(ItemModel).where(ItemModel.batch_id == batch_id)
    ).all()

    detail = S57ImportBatchDetail(
        id=batch.id,
        name=batch.name,
        status=batch.status,
        stage=batch.stage,
        progress=batch.progress,
        total_cells=batch.total_cells,
        processed_cells=batch.processed_cells,
        succeeded_cells=batch.succeeded_cells,
        failed_cells=batch.failed_cells,
        purpose=batch.purpose,
        metadata_json=batch.metadata_json,
        created_at=batch.created_at,
        started_at=batch.started_at,
        finished_at=batch.finished_at,
        items=[
            S57ImportBatchItemRead(
                id=item.id,
                batch_id=item.batch_id,
                cell_name=item.cell_name,
                status=item.status,
                stage=item.stage,
                progress=item.progress,
                update_count=item.update_count,
                current_update=item.current_update,
                dataset_id=item.dataset_id,
                error_code=item.error_code,
                error_message=item.error_message,
                finished_at=item.finished_at,
            )
            for item in items
        ],
    )
    return _enrich_batch_detail(detail)
