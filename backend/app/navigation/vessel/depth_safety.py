"""Draft + UKC depth safety with explicit UNKNOWN."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class DepthStatus(StrEnum):
    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    UNKNOWN = "UNKNOWN"

    def __bool__(self) -> bool:
        raise TypeError("DepthStatus cannot be used as a boolean; handle SAFE/UNSAFE/UNKNOWN")


class DepthSafetyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    depth_m: float | None
    draft_m: float
    ukc_m: float
    required_depth_m: float
    margin_m: float | None
    status: DepthStatus
    reason: str | None = None


def evaluate_depth(
    depth_m: float | None,
    *,
    draft_m: float,
    ukc_m: float,
) -> DepthSafetyResult:
    required = draft_m + ukc_m
    if depth_m is None:
        return DepthSafetyResult(
            depth_m=None,
            draft_m=draft_m,
            ukc_m=ukc_m,
            required_depth_m=required,
            margin_m=None,
            status=DepthStatus.UNKNOWN,
            reason="depth_unknown",
        )
    margin = float(depth_m) - required
    if float(depth_m) <= 0.0:
        return DepthSafetyResult(
            depth_m=float(depth_m),
            draft_m=draft_m,
            ukc_m=ukc_m,
            required_depth_m=required,
            margin_m=margin,
            status=DepthStatus.UNSAFE,
            reason="land_or_zero_depth",
        )
    if margin < 0.0:
        return DepthSafetyResult(
            depth_m=float(depth_m),
            draft_m=draft_m,
            ukc_m=ukc_m,
            required_depth_m=required,
            margin_m=margin,
            status=DepthStatus.UNSAFE,
            reason="insufficient_under_keel_clearance",
        )
    return DepthSafetyResult(
        depth_m=float(depth_m),
        draft_m=draft_m,
        ukc_m=ukc_m,
        required_depth_m=required,
        margin_m=margin,
        status=DepthStatus.SAFE,
        reason=None,
    )
