"""Static vessel profile API (no live vessel state)."""

from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import User
from app.navigation.schemas import DepthSafetyRead, VesselRead
from app.navigation.vessel.depth_safety import evaluate_depth
from app.navigation.vessel.service import VesselNotFound, VesselService

router = APIRouter(prefix="/navigation/vessels", tags=["navigation-vessels"])
settings = get_settings()

_service: VesselService | None = None
_service_lock = threading.Lock()


def get_vessel_service() -> VesselService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = VesselService()
    return _service


def ensure_navigation_enabled() -> None:
    if not settings.navigation_enabled:
        raise AppError("NAVIGATION_DISABLED", "导航功能未启用", 404)


def _vessel_read(vessel) -> VesselRead:
    return VesselRead(
        **vessel.model_dump(),
        required_depth_m=vessel.required_depth_m,
        live_state_available=False,
        live_state_note="未接入实时船位/航向/传感器数据",
    )


@router.get("", response_model=list[VesselRead])
def list_vessels(_user: User = Depends(get_current_user)) -> list[VesselRead]:
    ensure_navigation_enabled()
    return [_vessel_read(vessel) for vessel in get_vessel_service().list()]


@router.get("/{vessel_id}", response_model=VesselRead)
def get_vessel(
    vessel_id: str,
    _user: User = Depends(get_current_user),
) -> VesselRead:
    ensure_navigation_enabled()
    try:
        return _vessel_read(get_vessel_service().get(vessel_id))
    except VesselNotFound as error:
        raise AppError("VESSEL_NOT_FOUND", "船舶资料不存在", 404) from error


@router.get("/{vessel_id}/depth-safety", response_model=DepthSafetyRead)
def depth_safety(
    vessel_id: str,
    depth_m: float = Query(..., ge=0),
    _user: User = Depends(get_current_user),
) -> DepthSafetyRead:
    ensure_navigation_enabled()
    try:
        vessel = get_vessel_service().get(vessel_id)
    except VesselNotFound as error:
        raise AppError("VESSEL_NOT_FOUND", "船舶资料不存在", 404) from error
    result = evaluate_depth(depth_m, draft_m=vessel.safety_draft_m, ukc_m=vessel.ukc_m)
    return DepthSafetyRead(**result.model_dump())
