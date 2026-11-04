"""Project-scoped S-57 waterway thematic endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.projects import project_or_404
from app.core.database import get_db
from app.models import User
from app.schemas import (
    S57WaterwayCatalogRead,
    S57WaterwayDetailRead,
    S57WaterwayPreviewRequest,
    S57WaterwayPreviewResponse,
    S57WaterwaySearchRequest,
    S57WaterwaySearchResponse,
    S57WaterwaySnapshotCreateRequest,
    S57WaterwaySnapshotList,
    S57WaterwaySnapshotManifest,
)
from app.services import s57_waterway_export as snapshot_service
from app.services import s57_waterways as service

router = APIRouter(
    prefix="/projects/{project_id}/s57-waterways",
    tags=["s57-waterways"],
)


@router.get("/catalog", response_model=S57WaterwayCatalogRead)
def waterway_catalog(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    project = project_or_404(db, project_id, include_unpublished=False)
    return service.build_catalog(service.resolve_waterway_layers(db, project.id))


@router.post("/search", response_model=S57WaterwaySearchResponse)
def waterway_search(
    project_id: UUID,
    payload: S57WaterwaySearchRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    project = project_or_404(db, project_id, include_unpublished=False)
    return service.execute_waterway_search(db, project.id, payload)


@router.post("/preview", response_model=S57WaterwayPreviewResponse)
def waterway_preview(
    project_id: UUID,
    payload: S57WaterwayPreviewRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    project = project_or_404(db, project_id, include_unpublished=False)
    return snapshot_service.preview_waterway_items(db, project.id, payload)


@router.post(
    "/snapshots", response_model=S57WaterwaySnapshotManifest, status_code=201
)
def waterway_snapshot_create(
    project_id: UUID,
    payload: S57WaterwaySnapshotCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    project = project_or_404(db, project_id, include_unpublished=False)
    return snapshot_service.create_waterway_snapshot(db, project.id, payload)


@router.get("/snapshots", response_model=S57WaterwaySnapshotList)
def waterway_snapshot_list(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    project = project_or_404(db, project_id, include_unpublished=False)
    items, warnings = snapshot_service.list_snapshots(project.id)
    current_versions = snapshot_service.current_waterway_version_ids(db, project.id)
    return {
        "items": [
            snapshot_service.mark_snapshot_stale(manifest, current_versions)
            for manifest in items
        ],
        "warnings": warnings,
    }


@router.get(
    "/snapshots/{snapshot_id}", response_model=S57WaterwaySnapshotManifest
)
def waterway_snapshot_detail(
    project_id: UUID,
    snapshot_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    project = project_or_404(db, project_id, include_unpublished=False)
    manifest = snapshot_service.load_snapshot_manifest(project.id, snapshot_id)
    current_versions = snapshot_service.current_waterway_version_ids(db, project.id)
    return snapshot_service.mark_snapshot_stale(manifest, current_versions)


@router.get("/snapshots/{snapshot_id}/download")
def waterway_snapshot_download(
    project_id: UUID,
    snapshot_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> FileResponse:
    project = project_or_404(db, project_id, include_unpublished=False)
    path = snapshot_service.snapshot_geojson_path(project.id, snapshot_id)
    return FileResponse(
        path,
        media_type="application/geo+json",
        filename=f"waterways-{snapshot_id}.geojson",
    )


@router.get("/{feature_id}", response_model=S57WaterwayDetailRead)
def waterway_detail(
    project_id: UUID,
    feature_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    project = project_or_404(db, project_id, include_unpublished=False)
    return service.get_waterway_feature(db, project.id, feature_id)
