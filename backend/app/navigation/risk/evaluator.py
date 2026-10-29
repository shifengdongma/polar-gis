"""Versioned environment risk evaluation.

``legacy_v1`` reproduces the reference V3 formulas (research only).
``real_v1`` keeps the same component formulas but never turns missing data
into zero risk: unavailable components are excluded, ice/depth missing makes
the combined risk and traversability UNKNOWN, and planning fails loudly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from math import cos, radians, sin
from pathlib import Path
from typing import Literal

import numpy as np

from app.navigation.contracts import DataQuality
from app.navigation.vessel.models import VesselProfile

RiskModelVersion = Literal["legacy_v1", "real_v1"]

_WEIGHTS_PATH = Path(__file__).resolve().parents[1] / "resources" / "risk" / "weights_v1.json"


@dataclass(frozen=True)
class RiskInput:
    latitude: float
    longitude: float
    day_of_year: int
    depth_m: float | None
    ice_concentration: float | None
    ice_thickness_m: float | None
    wind_speed_ms: float | None
    wind_direction_from_deg: float | None
    wave_height_m: float | None
    wave_direction_from_deg: float | None
    current_u_ms: float | None
    current_v_ms: float | None
    quality: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskResult:
    ice_risk: float | None
    depth_risk: float | None
    fog_risk: float | None
    wind_risk: float | None
    wave_risk: float | None
    combined_risk: float | None
    traversable: bool | None
    blocked_reason: str | None
    quality: dict[str, str]
    combined_quality: str
    sources: dict[str, str]
    model_version: str

    @property
    def components(self) -> dict[str, float | None]:
        return {
            "ice": self.ice_risk,
            "depth": self.depth_risk,
            "fog": self.fog_risk,
            "wind": self.wind_risk,
            "wave": self.wave_risk,
        }


@dataclass(frozen=True)
class _Weights:
    weights: dict[str, float]
    ice_floor: float
    multi_year_factor: float
    multi_year_threshold: float
    load_offset: float
    load_scale: float
    blocked_load: float
    ukc_default: float
    depth_margin: float
    wind_threshold: float
    wind_margin: float
    wind_offset: float
    wave_threshold: float
    wave_margin: float
    wave_offset: float


@lru_cache
def _weights() -> _Weights:
    payload = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    return _Weights(
        weights={key: float(value) for key, value in payload["weights"].items()},
        ice_floor=float(payload["ice"]["thickness_cap_floor_m"]),
        multi_year_factor=float(payload["ice"]["multi_year_factor"]),
        multi_year_threshold=float(payload["ice"]["multi_year_threshold_m"]),
        load_offset=float(payload["ice"]["load_offset"]),
        load_scale=float(payload["ice"]["load_scale"]),
        blocked_load=float(payload["ice"]["blocked_load"]),
        ukc_default=float(payload["depth"]["ukc_default_m"]),
        depth_margin=float(payload["depth"]["warning_margin_m"]),
        wind_threshold=float(payload["wind"]["threshold_ms"]),
        wind_margin=float(payload["wind"]["margin_ms"]),
        wind_offset=float(payload["wind"]["instant_offset_ms"]),
        wave_threshold=float(payload["wave"]["threshold_m"]),
        wave_margin=float(payload["wave"]["margin_m"]),
        wave_offset=float(payload["wave"]["instant_offset_m"]),
    )


def phase_radians(latitude: float, longitude: float, day_of_year: int) -> float:
    return radians(latitude * 2.7 + longitude * 0.83 + day_of_year * 3.1)


def evaluate_risk(
    payload: RiskInput,
    vessel: VesselProfile,
    version: RiskModelVersion = "legacy_v1",
) -> RiskResult:
    weights = _weights()
    quality = dict(payload.quality)
    sources = dict(payload.sources)
    phase = phase_radians(payload.latitude, payload.longitude, payload.day_of_year)

    ice_risk, ice_blocked, ice_state = _ice_risk(payload, vessel, version, weights)
    depth_risk, depth_blocked, depth_state = _depth_risk(payload, vessel, version, weights)
    fog_risk = _fog_risk(phase, version)
    wind_risk = _wind_risk(payload.wind_speed_ms, phase, version, weights)
    wave_risk = _wave_risk(payload.wave_height_m, phase, version, weights)
    if version == "real_v1":
        # No historical-frequency provider is migrated; record the missing
        # prior instead of silently treating it as zero risk evidence.
        quality.setdefault("wind_prior", DataQuality.MISSING.value)
        quality.setdefault("wave_prior", DataQuality.MISSING.value)

    if version == "legacy_v1":
        components = {
            "ice": 0.5 if ice_risk is None else ice_risk,
            "depth": 1.0 if depth_risk is None else depth_risk,
            "fog": 0.0 if fog_risk is None else fog_risk,
            "wind": 0.0 if wind_risk is None else wind_risk,
            "wave": 0.0 if wave_risk is None else wave_risk,
        }
        combined = float(sum(weights.weights[name] * value for name, value in components.items()))
        traversable = not ice_blocked and not depth_blocked
        combined_quality = DataQuality.SYNTHETIC.value if any(
            quality.get(name) == DataQuality.SYNTHETIC.value for name in components
        ) else DataQuality.REAL.value
        blocked_reason = _blocked_reason(ice_blocked, depth_blocked, ice_state, depth_state)
    else:
        components = {
            "ice": ice_risk,
            "depth": depth_risk,
            "fog": fog_risk,
            "wind": wind_risk,
            "wave": wave_risk,
        }
        if ice_risk is None or depth_risk is None:
            combined = None
            traversable = None
        else:
            available = {name: value for name, value in components.items() if value is not None}
            total_weight = sum(weights.weights[name] for name in available)
            combined = (
                float(sum(weights.weights[name] * value for name, value in available.items()) / total_weight)
                if total_weight > 0
                else None
            )
            traversable = not ice_blocked and not depth_blocked
        combined_quality = (
            DataQuality.UNKNOWN.value
            if combined is None
            else (
                DataQuality.UNKNOWN.value
                if any(value is None for value in components.values())
                else DataQuality.REAL.value
            )
        )
        blocked_reason = _blocked_reason(ice_blocked, depth_blocked, ice_state, depth_state)

    return RiskResult(
        ice_risk=ice_risk,
        depth_risk=depth_risk,
        fog_risk=fog_risk,
        wind_risk=wind_risk,
        wave_risk=wave_risk,
        combined_risk=combined,
        traversable=traversable,
        blocked_reason=blocked_reason,
        quality=quality,
        combined_quality=combined_quality,
        sources=sources,
        model_version=version,
    )


def _ice_risk(
    payload: RiskInput,
    vessel: VesselProfile,
    version: RiskModelVersion,
    weights: _Weights,
) -> tuple[float | None, bool, str]:
    if payload.ice_concentration is None or payload.ice_thickness_m is None:
        if version == "legacy_v1":
            return 0.5, False, "missing"
        return None, False, "unknown"
    concentration = float(payload.ice_concentration)
    thickness = float(payload.ice_thickness_m)
    capability = max(vessel.continuous_ice_thickness_m, weights.ice_floor)
    multi_year = weights.multi_year_factor if thickness > weights.multi_year_threshold else 1.0
    load = concentration * (0.35 + 0.65 * min(thickness / capability, 1.5)) * multi_year
    risk = float(np.clip((load - weights.load_offset) / weights.load_scale, 0.0, 1.0))
    return risk, bool(load >= weights.blocked_load), "ice_load" if load >= weights.blocked_load else "ok"


def _depth_risk(
    payload: RiskInput,
    vessel: VesselProfile,
    version: RiskModelVersion,
    weights: _Weights,
) -> tuple[float | None, bool, str]:
    required = vessel.required_depth_m
    if payload.depth_m is None:
        return (1.0, True, "missing") if version == "legacy_v1" else (None, True, "unknown")
    depth = float(payload.depth_m)
    if depth <= 0.0:
        return 1.0, True, "land"
    if depth < required:
        return 1.0, True, "shallow"
    risk = float(np.clip((required + weights.depth_margin - depth) / weights.depth_margin, 0.0, 1.0))
    return risk, False, "ok"


def _fog_risk(phase: float, version: RiskModelVersion) -> float | None:
    if version == "real_v1":
        return None
    return float(np.clip(0.18 + 0.18 * sin(phase + 1.4), 0.0, 1.0))


def _threshold_risk(value: float, threshold: float, margin: float, frequency: float) -> float:
    instantaneous = np.clip((value - (threshold - margin)) / max(margin, 1e-9), 0.0, 1.0)
    return float(np.clip(max(float(instantaneous), float(frequency)), 0.0, 1.0))


def _wind_risk(
    speed: float | None,
    phase: float,
    version: RiskModelVersion,
    weights: _Weights,
) -> float | None:
    if speed is None:
        return None
    if version == "legacy_v1":
        frequency = float(np.clip(0.35 + 0.25 * sin(phase * 0.77), 0.0, 1.0))
        return _threshold_risk(
            float(speed), weights.wind_threshold, weights.wind_margin, frequency
        )
    # real_v1 has no historical-frequency provider; the instantaneous value is
    # used alone and the missing prior is recorded in component quality.
    instantaneous = float(
        np.clip(
            (float(speed) - weights.wind_offset) / max(weights.wind_margin, 1e-9), 0.0, 1.0
        )
    )
    return instantaneous


def _wave_risk(
    height: float | None,
    phase: float,
    version: RiskModelVersion,
    weights: _Weights,
) -> float | None:
    if height is None:
        return None
    if version == "legacy_v1":
        frequency = float(np.clip(0.12 + 0.2 * cos(phase * 0.51), 0.0, 1.0))
        return _threshold_risk(
            float(height), weights.wave_threshold, weights.wave_margin, frequency
        )
    instantaneous = float(
        np.clip(
            (float(height) - weights.wave_offset) / max(weights.wave_margin, 1e-9), 0.0, 1.0
        )
    )
    return instantaneous


def _blocked_reason(
    ice_blocked: bool,
    depth_blocked: bool,
    ice_state: str,
    depth_state: str,
) -> str | None:
    if depth_blocked:
        return "land" if depth_state == "land" else "shallow_water"
    if ice_blocked:
        return "ice_load"
    return None


def risk_component_quality(result: RiskResult) -> dict[str, str]:
    """Expose component quality without pretending unknown values are zero."""
    quality = dict(result.quality)
    for name, value in result.components.items():
        if value is None:
            quality[name] = DataQuality.MISSING.value
    if result.combined_risk is None:
        quality["combined"] = DataQuality.UNKNOWN.value
    elif result.combined_quality == DataQuality.UNKNOWN.value:
        quality["combined"] = DataQuality.UNKNOWN.value
    else:
        quality["combined"] = result.combined_quality
    return quality
