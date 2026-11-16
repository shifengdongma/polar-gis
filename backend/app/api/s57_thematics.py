"""Project-scoped S-57 depth/hazard thematic export endpoints."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.api.deps import get_current_user
from app.api.projects import project_or_404
from app.core.database import get_db
from app.core.errors import AppError
from app.models import User
from app.schemas import (
    S57ThematicCatalogRead,
    S57ThematicExportCreateRequest,
    S57ThematicExportList,
    S57ThematicExportManifest,
)
from app.services import s57_thematic_catalog as catalog_service
from app.services import s57_thematic_export as export_service

router = APIRouter(
    prefix="/projects/{project_id}/s57-thematics",
    tags=["s57-thematics"],
)


def _remove_file(path: Path) -> None:
    path.unlink(missing_ok=True)


def _stale_manifest(
    db: Session, project_id: UUID, manifest: dict
) -> dict:
    current_versions = export_service.current_thematic_version_ids(db, project_id)
    return export_service.mark_thematic_export_stale(manifest, current_versions)


@router.get("/catalog", response_model=S57ThematicCatalogRead)
def thematic_catalog(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    project = project_or_404(db, project_id, include_unpublished=False)
    return catalog_service.build_thematic_catalog(db, project.id)


@router.post(
    "/exports", response_model=S57ThematicExportManifest, status_code=201
)
def thematic_export_create(
    project_id: UUID,
    payload: S57ThematicExportCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    project = project_or_404(db, project_id, include_unpublished=False)
    return export_service.create_thematic_export(db, project.id, payload)


@router.get("/exports", response_model=S57ThematicExportList)
def thematic_export_list(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    project = project_or_404(db, project_id, include_unpublished=False)
    items, warnings = export_service.list_thematic_exports(project.id)
    current_versions = export_service.current_thematic_version_ids(db, project.id)
    return {
        "items": [
            export_service.mark_thematic_export_stale(manifest, current_versions)
            for manifest in items
        ],
        "warnings": warnings,
    }


@router.get(
    "/exports/{export_id}/download",
    response_class=FileResponse,
)
def thematic_export_download(
    project_id: UUID,
    export_id: str,
    file: str | None = Query(default=None),
    format: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    project = project_or_404(db, project_id, include_unpublished=False)
    if file:
        path = export_service.thematic_file_path(project.id, export_id, file)
        return FileResponse(
            path,
            media_type="application/geo+json",
            filename=path.name,
        )
    if format not in (None, "geojson", "zip"):
        raise AppError(
            "S57_THEMATIC_DOWNLOAD_INVALID",
            "下载格式仅支持 geojson 或 zip",
            422,
        )
    manifest = export_service.load_thematic_export(project.id, export_id)
    data_files = manifest.get("files") or []
    if format == "geojson" and len(data_files) > 1:
        raise AppError(
            "S57_THEMATIC_DOWNLOAD_INVALID",
            "该成果包含多个 GeoJSON 文件，请使用 ZIP 或通过 file 参数指定文件",
            422,
        )
    if format != "zip" and len(data_files) == 1:
        relative = str(data_files[0].get("path") or "")
        path = export_service.thematic_file_path(project.id, export_id, relative)
        return FileResponse(
            path,
            media_type="application/geo+json",
            filename=path.name,
        )
    if not data_files:
        raise AppError(
            "S57_THEMATIC_EXPORT_NOT_FOUND",
            "专题成果没有可下载的数据文件",
            404,
        )
    zip_path, filename = export_service.build_thematic_zip(project.id, export_id)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(_remove_file, zip_path),
    )


@router.get("/exports/{export_id}/preview", response_class=FileResponse)
def thematic_export_preview(
    project_id: UUID,
    export_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    project = project_or_404(db, project_id, include_unpublished=False)
    manifest = export_service.load_thematic_export(project.id, export_id)
    preview = manifest.get("preview")
    if not isinstance(preview, dict) or not preview.get("path"):
        raise AppError(
            "S57_THEMATIC_EXPORT_NOT_FOUND",
            "该专题成果没有样例预览文件",
            404,
        )
    path = export_service.thematic_file_path(
        project.id, export_id, str(preview["path"])
    )
    return FileResponse(
        path,
        media_type="application/geo+json",
        filename=f"preview-{export_id}.geojson",
    )


@router.get(
    "/exports/{export_id}", response_model=S57ThematicExportManifest
)
def thematic_export_detail(
    project_id: UUID,
    export_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    project = project_or_404(db, project_id, include_unpublished=False)
    manifest = export_service.load_thematic_export(project.id, export_id)
    return _stale_manifest(db, project.id, manifest)
