"""Area risk evaluation without route optimization."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.navigation_plans import _ensure_enabled, _run_read, get_task_service
from app.api.projects import project_or_404
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models import Role, User
from app.navigation.contracts import ensure_utc
from app.navigation.planner.static_grid import PlanningGridUnavailable, load_static_grid
from app.navigation.schemas import PlanningRunRead, RiskEvaluateRequest
from app.navigation.tasks.errors import PlanningTaskError
from app.navigation.vessel.service import VesselNotFound, VesselService

router = APIRouter(prefix="/navigation", tags=["navigation-risk"])
settings = get_settings()


@router.post("/risk/evaluate", response_model=PlanningRunRead, status_code=202)
def evaluate_area(
    payload: RiskEvaluateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanningRunRead:
    _ensure_enabled()
    project = project_or_404(
        db,
        payload.project_id,
        include_unpublished=user.role == Role.SYSTEM_ADMIN.value,
    )
    try:
        departure = ensure_utc(payload.departure_time)
    except ValueError as error:
        raise AppError("INPUT_INVALID", "时间必须包含时区", 422) from error
    west, south, east, north = payload.bbox
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south < north <= 90):
        raise AppError("INPUT_INVALID", "bbox 范围无效", 422)
    try:
        VesselService().get(payload.vessel_id)
    except VesselNotFound as error:
        raise AppError("VESSEL_NOT_FOUND", "船舶资料不存在", 404) from error
    try:
        static = load_static_grid()
    except PlanningGridUnavailable as error:
        raise AppError("PLANNING_GRID_MISSING", str(error), 503) from error
    cells = static.viewport_indices((west, south, east, north))
    if not cells:
        raise AppError("INPUT_INVALID", "所选区域不在东北航道规划网格内", 422)
    if len(cells) > settings.planner_max_cells:
        raise AppError("PLANNER_LIMIT_EXCEEDED", "所选区域栅格数超过配置上限", 422)
    center_lon = (west + east) / 2.0 if west <= east else ((west + east + 360.0) / 2.0) % 360.0 - 180.0
    center_lat = (south + north) / 2.0
    request_payload = {
        "bbox": [west, south, east, north],
        "departureTime": departure.isoformat().replace("+00:00", "Z"),
        "vesselId": payload.vessel_id,
        "dataPolicy": payload.data_policy,
        "start": {"longitude": center_lon, "latitude": center_lat},
        "goal": {"longitude": center_lon, "latitude": center_lat},
    }
    try:
        run = get_task_service().create_run(
            db,
            project_id=project.id,
            requested_by=user.id,
            vessel_id=payload.vessel_id,
            mode="risk_only",
            data_policy=payload.data_policy,
            request_payload=request_payload,
            departure=departure,
        )
    except PlanningTaskError as error:
        raise AppError(error.code, str(error), error.status_code, error.details) from error
    return _run_read(run)
