"""Project-scoped S-57 waterway thematic endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.projects import project_or_404
from app.core.database import get_db
from app.models import User
from app.schemas import (
    S57WaterwayCatalogRead,
    S57WaterwayDetailRead,
    S57WaterwaySearchRequest,
    S57WaterwaySearchResponse,
)
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


@router.get("/{feature_id}", response_model=S57WaterwayDetailRead)
def waterway_detail(
    project_id: UUID,
    feature_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    project = project_or_404(db, project_id, include_unpublished=False)
    return service.get_waterway_feature(db, project.id, feature_id)
