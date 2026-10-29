"""Planning task API: create/read/cancel, routes, risk grid, route evaluation."""

from __future__ import annotations

import gzip
import json
import math
import threading
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.projects import project_or_404
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models import PlanningRun, Role, User
from app.navigation.contracts import ensure_utc
from app.navigation.environment.service import EnvironmentService
from app.navigation.planner.service import PlannerService
from app.navigation.planner.static_grid import PlanningGridUnavailable, load_static_grid
from app.navigation.schemas import (
    EvaluateRouteRead,
    EvaluateRouteRequest,
    PlanningCreateRequest,
    PlanningRenameRequest,
    PlanningRouteRead,
    PlanningRunRead,
)
from app.navigation.tasks.errors import PlanningNotFound, PlanningTaskError
from app.navigation.tasks.service import PlanningTaskService
from app.navigation.vessel.service import VesselNotFound, VesselService
from app.schemas import Paginated

router = APIRouter(prefix="/navigation/plans", tags=["navigation-plans"])
settings = get_settings()

_task_service: PlanningTaskService | None = None
_task_lock = threading.Lock()


def get_task_service() -> PlanningTaskService:
    global _task_service
    if _task_service is None:
        with _task_lock:
            if _task_service is None:
                _task_service = PlanningTaskService(settings)
    return _task_service


def _ensure_enabled() -> None:
    if not settings.navigation_enabled:
        raise AppError("NAVIGATION_DISABLED", "导航功能未启用", 404)


def _run_read(run: PlanningRun) -> PlanningRunRead:
    return PlanningRunRead(
        plan_id=run.id,
        project_id=run.project_id,
        title=run.title,
        vessel_id=run.vessel_id,
        mode=run.mode,
        status=run.status,
        stage=run.stage,
        progress=run.progress,
        data_policy=run.data_policy,
        risk_model_version=run.risk_model_version,
        algorithm_version=run.algorithm_version,
        error_code=run.error_code,
        error_message=run.error_message,
        result_summary=run.result_summary_json or {},
        environment_snapshot=run.environment_snapshot_json or {},
        cancel_requested=run.cancel_requested,
        queued_at=run.queued_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
    )


def _route_read(run_id: UUID, route) -> PlanningRouteRead:
    return PlanningRouteRead(
        route_id=route.route_id,
        plan_id=run_id,
        route_index=route.route_index,
        label=route.label,
        recommended=route.is_recommended,
        coordinates=route.coordinates_json or [],
        risk_score=route.risk_score,
        risk_components={
            "ice": route.ice_risk,
            "depth": route.depth_risk,
            "fog": route.fog_risk,
            "wind": route.wind_risk,
            "wave": route.wave_risk,
        },
        energy_mwh=route.energy_mwh,
        time_hours=route.time_hours,
        distance_km=route.distance_km,
        source_quality=route.quality,
        algorithm_version=route.algorithm_version,
        created_at=route.created_at,
    )


def _run_for_user(db: Session, plan_id: UUID, user: User) -> PlanningRun:
    try:
        run = get_task_service().get_run(db, plan_id)
    except PlanningNotFound as error:
        raise AppError(error.code, str(error), error.status_code) from error
    project_or_404(
        db,
        run.project_id,
        include_unpublished=user.role == Role.SYSTEM_ADMIN.value,
    )
    return run


def _read_risk_grid(run: PlanningRun) -> dict[str, object]:
    if not run.risk_grid_path:
        raise AppError("PLANNER_RESULT_NOT_READY", "风险栅格尚未生成", 409)
    path = get_task_service().result_root / Path(run.risk_grid_path).name
    if not path.is_file():
        raise AppError("PLANNER_RESULT_NOT_READY", "风险栅格文件缺失", 409)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        payload["snapshotId"] = str(run.id)
    return payload


@router.post("", response_model=PlanningRunRead, status_code=202)
def create_plan(
    payload: PlanningCreateRequest,
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
        raise AppError("INPUT_INVALID", "出发时间必须包含时区", 422) from error
    try:
        VesselService().get(payload.vessel_id)
    except VesselNotFound as error:
        raise AppError("VESSEL_NOT_FOUND", "船舶资料不存在", 404) from error
    objectives = set(payload.objectives)
    if objectives != {"risk", "energy", "time"}:
        raise AppError("INPUT_INVALID", "目标必须且只能是 risk/energy/time", 422)
    if payload.generations > settings.planner_max_generations:
        raise AppError("PLANNER_LIMIT_EXCEEDED", "迭代代数超过配置上限", 422)
    _validate_synthetic_overrides(payload.synthetic_overrides, payload.data_policy)
    try:
        static = load_static_grid()
    except PlanningGridUnavailable as error:
        raise AppError("PLANNING_GRID_MISSING", str(error), 503) from error
    start = (payload.start.longitude, payload.start.latitude)
    goal = (payload.goal.longitude, payload.goal.latitude)
    if start == goal:
        raise AppError("INPUT_INVALID", "起点与终点不能相同", 422)
    if static.nearest_cell(start[1], start[0]) is None or static.nearest_cell(goal[1], goal[0]) is None:
        raise AppError("INPUT_INVALID", "起点或终点不在东北航道规划网格内", 422)
    request_payload = payload.model_dump(mode="json", by_alias=True)
    try:
        run = get_task_service().create_run(
            db,
            project_id=project.id,
            requested_by=user.id,
            vessel_id=payload.vessel_id,
            mode="plan",
            data_policy=payload.data_policy,
            request_payload=request_payload,
            departure=departure,
            title=payload.title,
        )
    except PlanningTaskError as error:
        raise AppError(error.code, str(error), error.status_code, error.details) from error
    return _run_read(run)


@router.get("", response_model=Paginated[PlanningRunRead])
def list_plans(
    project_id: UUID = Query(...),
    status: str | None = Query(None, pattern=r"^(queued|running|completed|failed|cancelled)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Paginated[PlanningRunRead]:
    _ensure_enabled()
    project_or_404(
        db,
        project_id,
        include_unpublished=user.role == Role.SYSTEM_ADMIN.value,
    )
    runs, total = get_task_service().list_runs(
        db, project_id=project_id, status=status, page=page, page_size=page_size
    )
    return Paginated(
        items=[_run_read(run) for run in runs],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{plan_id}", response_model=PlanningRunRead)
def get_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanningRunRead:
    _ensure_enabled()
    return _run_read(_run_for_user(db, plan_id, user))


@router.patch("/{plan_id}", response_model=PlanningRunRead)
def rename_plan(
    plan_id: UUID,
    payload: PlanningRenameRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanningRunRead:
    _ensure_enabled()
    run = _run_for_user(db, plan_id, user)
    _require_owner(run, user)
    try:
        run = get_task_service().rename(db, run, payload.title)
    except PlanningTaskError as error:
        raise AppError(error.code, str(error), error.status_code) from error
    return _run_read(run)


@router.delete("/{plan_id}", status_code=204)
def delete_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    _ensure_enabled()
    run = _run_for_user(db, plan_id, user)
    _require_owner(run, user)
    try:
        get_task_service().delete(db, run)
    except PlanningTaskError as error:
        raise AppError(error.code, str(error), error.status_code) from error
    return Response(status_code=204)


@router.get("/{plan_id}/routes", response_model=list[PlanningRouteRead])
def get_routes(
    plan_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PlanningRouteRead]:
    _ensure_enabled()
    run = _run_for_user(db, plan_id, user)
    return [_route_read(run.id, route) for route in get_task_service().routes(db, run.id)]


@router.get("/{plan_id}/routes/{route_id}", response_model=PlanningRouteRead)
def get_route(
    plan_id: UUID,
    route_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanningRouteRead:
    _ensure_enabled()
    run = _run_for_user(db, plan_id, user)
    try:
        route = get_task_service().get_route(db, run.id, route_id)
    except PlanningNotFound as error:
        raise AppError(error.code, str(error), error.status_code) from error
    return _route_read(run.id, route)


@router.get("/{plan_id}/risk-grid")
def get_risk_grid(
    plan_id: UUID,
    field: str = Query("combined", pattern=r"^(combined|ice|depth|fog|wind|wave)$"),
    bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat"),
    stride: int = Query(1, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    _ensure_enabled()
    run = _run_for_user(db, plan_id, user)
    payload = _read_risk_grid(run)
    cells = payload.get("cells", [])
    if not isinstance(cells, list):
        raise AppError("PLANNER_RESULT_NOT_READY", "风险栅格格式无效", 409)
    parsed_bbox = _parse_bbox(bbox)
    selected = [
        cell
        for cell in cells
        if isinstance(cell, dict) and _cell_in_bbox(cell, parsed_bbox)
    ]
    selected = selected[::stride]
    if len(selected) > settings.planner_risk_grid_max_cells:
        auto_stride = math.ceil(len(selected) / settings.planner_risk_grid_max_cells)
        selected = selected[::auto_stride]
    features = []
    for cell in selected:
        risk = cell.get("risk") or {}
        value = risk.get(field) if isinstance(risk, dict) else None
        quality = cell.get("quality") or {}
        geometry = cell.get("geometry") or []
        ring = [[float(point[0]), float(point[1])] for point in geometry]
        if ring and ring[0] != ring[-1]:
            ring.append(ring[0])
        features.append(
            {
                "type": "Feature",
                "id": cell.get("cellId"),
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {
                    "cellId": cell.get("cellId"),
                    "value": value,
                    "traversable": cell.get("traversable"),
                    "quality": quality.get("combined") if isinstance(quality, dict) else None,
                    "riskModelVersion": cell.get("riskModelVersion"),
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "field": field,
        "totalCells": len(cells),
        "returnedCells": len(features),
        "snapshotTime": (run.environment_snapshot_json or {}).get("requested_time")
        or (run.environment_snapshot_json or {}).get("requestedTime"),
        "features": features,
    }


@router.get("/{plan_id}/risk-grid/{cell_id}")
def get_risk_cell(
    plan_id: UUID,
    cell_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    _ensure_enabled()
    run = _run_for_user(db, plan_id, user)
    payload = _read_risk_grid(run)
    for cell in payload.get("cells", []):
        if isinstance(cell, dict) and cell.get("cellId") == cell_id:
            return cell
    raise AppError("RISK_CELL_NOT_FOUND", "风险单元不存在", 404)


@router.post("/{plan_id}/cancel", response_model=PlanningRunRead)
def cancel_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanningRunRead:
    _ensure_enabled()
    run = _run_for_user(db, plan_id, user)
    if user.role != Role.SYSTEM_ADMIN.value and run.requested_by != user.id:
        raise AppError("FORBIDDEN", "只有任务创建者或管理员可以取消", 403)
    try:
        run = get_task_service().cancel(db, run)
    except PlanningTaskError as error:
        raise AppError(error.code, str(error), error.status_code) from error
    return _run_read(run)


@router.post("/{plan_id}/evaluate-route", response_model=EvaluateRouteRead)
def evaluate_route(
    plan_id: UUID,
    payload: EvaluateRouteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EvaluateRouteRead:
    _ensure_enabled()
    run = _run_for_user(db, plan_id, user)
    risk_grid = _read_risk_grid(run)
    coordinates: list[tuple[float, float]] = []
    for point in payload.coordinates:
        if len(point) != 2 or not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
            raise AppError("INPUT_INVALID", "航路坐标必须是 [经度, 纬度]", 422)
        coordinates.append((float(point[0]), float(point[1])))
    try:
        vessel = VesselService().get(run.vessel_id)
        service = PlannerService(EnvironmentService(settings), VesselService())
        result = service.evaluate_route(risk_grid, coordinates, vessel)
    except Exception as error:  # noqa: BLE001
        raise AppError("PLANNER_FAILED", f"航路重评失败: {error}", 422) from error
    return EvaluateRouteRead(
        traversable=bool(result.get("traversable")),
        risk_score=result.get("riskScore"),
        energy_mwh=result.get("energyMWh"),
        time_hours=result.get("timeHours"),
        distance_km=result.get("distanceKm"),
        source_quality=result.get("sourceQuality"),
        cell_ids=result.get("cellIds") or [],
        reason=result.get("reason"),
        blocked_cell_id=result.get("blockedCellId"),
        snapshot_id=result.get("snapshotId"),
    )


def _require_owner(run: PlanningRun, user: User) -> None:
    if user.role != Role.SYSTEM_ADMIN.value and run.requested_by != user.id:
        raise AppError("FORBIDDEN", "只有任务创建者或管理员可以修改", 403)


_OVERRIDE_RANGES: dict[str, tuple[float, float]] = {
    "depthM": (0.0, 12_000.0),
    "iceConcentration": (0.0, 1.0),
    "iceThicknessM": (0.0, 20.0),
    "windSpeedMs": (0.0, 80.0),
    "windDirectionFromDeg": (0.0, 360.0),
    "currentSpeedMs": (0.0, 5.0),
    "currentDirectionToDeg": (0.0, 360.0),
    "waveHeightM": (0.0, 30.0),
    "wavePeriodS": (0.0, 40.0),
    "waveDirectionFromDeg": (0.0, 360.0),
}


def _validate_synthetic_overrides(
    overrides: dict[str, float] | None,
    data_policy: str,
) -> None:
    if not overrides:
        return
    if data_policy != "allow_synthetic_research":
        raise AppError(
            "INPUT_INVALID", "合成环境值覆盖仅适用于 allow_synthetic_research", 422
        )
    for key, value in overrides.items():
        limits = _OVERRIDE_RANGES.get(key)
        if limits is None:
            raise AppError("INPUT_INVALID", f"未知的合成覆盖字段: {key}", 422)
        if not math.isfinite(value) or not (limits[0] <= value <= limits[1]):
            raise AppError(
                "INPUT_INVALID",
                f"合成覆盖字段 {key} 超出范围 [{limits[0]}, {limits[1]}]",
                422,
            )


def _parse_bbox(value: str | None) -> tuple[float, float, float, float] | None:
    if not value:
        return None
    parts = value.split(",")
    if len(parts) != 4:
        raise AppError("INPUT_INVALID", "bbox 必须是 minLon,minLat,maxLon,maxLat", 422)
    try:
        return tuple(float(part) for part in parts)  # type: ignore[return-value]
    except ValueError as error:
        raise AppError("INPUT_INVALID", "bbox 数值无效", 422) from error


def _cell_in_bbox(
    cell: dict[str, object],
    bbox: tuple[float, float, float, float] | None,
) -> bool:
    if bbox is None:
        return True
    center = cell.get("center")
    if not isinstance(center, dict):
        return False
    longitude = float(center["longitude"])
    latitude = float(center["latitude"])
    west, south, east, north = bbox
    lon_ok = west <= longitude <= east if west <= east else longitude >= west or longitude <= east
    return lon_ok and south <= latitude <= north
