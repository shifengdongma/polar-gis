"""Directional edge transit model with vessel-specific speed/power limits.

The planner evaluates an edge once and reuses the result for risk, energy, and
time.  It is the only place that computes these values; routes, risks and the
comparison table all read this result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.navigation.vessel.models import VesselProfile

if TYPE_CHECKING:
    from .grid import PlanningGrid, Point

KN_TO_MPS = 0.514444
KM_PER_NM = 1.852
GROUND_MIN_SPEED_KN = 0.5
OPEN_WATER_REFERENCE_POWER_MW = 3.6
ICE_RESISTANCE_REFERENCE_N = 2.187483e6
ICE_REFERENCE_THICKNESS_M = 1.5
ICE_REFERENCE_SPEED_KN = 3.0
ICE_PROPULSION_EFFICIENCY = 0.225
OPEN_WATER_EFFICIENCY = 0.60


@dataclass(frozen=True, slots=True)
class PowerComponents:
    calm_mw: float
    ice_mw: float
    wind_mw: float
    wave_mw: float

    @property
    def total_mw(self) -> float:
        return self.calm_mw + self.ice_mw + self.wind_mw + self.wave_mw


@dataclass(frozen=True, slots=True)
class EdgeTransitResult:
    feasible: bool
    risk: float
    distance_km: float
    speed_through_water_kn: float
    current_along_track_kn: float
    speed_over_ground_kn: float
    calm_power_mw: float
    ice_power_mw: float
    wind_power_mw: float
    wave_power_mw: float
    total_power_mw: float
    travel_time_h: float
    energy_mwh: float
    power_limited: bool
    power_limit_mw: float
    reason: str | None = None

    @property
    def power_utilization(self) -> float:
        return self.total_power_mw / self.power_limit_mw if self.power_limit_mw else math.inf


def _env_value(cell: dict[str, object], name: str, default: float = 0.0) -> float:
    environment = cell.get("environment")
    if not isinstance(environment, dict):
        return default
    value = environment.get(name)
    try:
        return default if value is None else float(value)
    except (TypeError, ValueError):
        return default


def _heading(grid: PlanningGrid, a: Point, b: Point) -> tuple[float, float]:
    lat1, lon1 = grid.coordinate(a)
    lat2, lon2 = grid.coordinate(b)
    phi = math.radians((lat1 + lat2) * 0.5)
    longitude_delta = (lon2 - lon1 + 180.0) % 360.0 - 180.0
    east = longitude_delta * math.cos(phi)
    north = lat2 - lat1
    length = math.hypot(east, north)
    return (east / length, north / length) if length else (0.0, 0.0)


def _power_components(
    concentration: float,
    thickness_m: float,
    speed_kn: float,
    wind_u_mps: float,
    wind_v_mps: float,
    wave_height_m: float,
    wave_direction_deg: float,
    heading: tuple[float, float],
    vessel: VesselProfile,
) -> PowerComponents:
    speed_mps = speed_kn * KN_TO_MPS
    calm = OPEN_WATER_REFERENCE_POWER_MW * (
        speed_kn / max(vessel.reference_speed_kn, 1e-9)
    ) ** 3

    ice = 0.0
    if concentration >= 0.05 and thickness_m >= 0.05:
        resistance = ICE_RESISTANCE_REFERENCE_N * concentration**1.5
        resistance *= thickness_m / ICE_REFERENCE_THICKNESS_M
        resistance *= (max(speed_kn, 0.0) / ICE_REFERENCE_SPEED_KN) ** 0.3
        ice = resistance * speed_mps / ICE_PROPULSION_EFFICIENCY / 1e6

    ship_u = speed_mps * heading[0]
    ship_v = speed_mps * heading[1]
    relative_u = wind_u_mps - ship_u
    relative_v = wind_v_mps - ship_v
    relative_speed = math.hypot(relative_u, relative_v)
    wind_speed = math.hypot(wind_u_mps, wind_v_mps)
    wind = 0.0
    if relative_speed > 0.0 and wind_speed > 0.0:
        wind_alignment = (wind_u_mps * heading[0] + wind_v_mps * heading[1]) / wind_speed
        direction_factor = 0.5 * (1.0 - max(-1.0, min(1.0, wind_alignment)))
        wind_resistance = 0.5 * 1.225 * 0.8 * 400.0 * relative_speed**2 * direction_factor
        wind = wind_resistance * speed_mps / OPEN_WATER_EFFICIENCY / 1e6

    wave_to_deg = (wave_direction_deg + 180.0) % 360.0
    wave_rad = math.radians(90.0 - wave_to_deg)
    wave_heading_dot = math.cos(wave_rad) * heading[0] + math.sin(wave_rad) * heading[1]
    wave_factor = 0.25 + 0.375 * (1.0 - max(-1.0, min(1.0, wave_heading_dot)))
    wave_resistance = (
        0.02 * 1025.0 * 9.81 * 22.3 * max(wave_height_m, 0.0) ** 2 * wave_factor
    )
    wave = wave_resistance * speed_mps / OPEN_WATER_EFFICIENCY / 1e6
    return PowerComponents(calm, ice, wind, wave)


def _midpoint(grid: PlanningGrid, a: Point, b: Point, name: str, default: float = 0.0) -> float:
    first = grid.cell_metadata.get(a, {})
    second = grid.cell_metadata.get(b, {})
    return 0.5 * (_env_value(first, name, default) + _env_value(second, name, default))


def required_power_mw(
    grid: PlanningGrid, a: Point, b: Point, speed_kn: float
) -> float:
    components = _power_components(
        _midpoint(grid, a, b, "ice_concentration"),
        _midpoint(grid, a, b, "ice_thickness_m"),
        speed_kn,
        _midpoint(grid, a, b, "wind_u_ms"),
        _midpoint(grid, a, b, "wind_v_ms"),
        _midpoint(grid, a, b, "wave_height_m"),
        _midpoint(grid, a, b, "wave_direction_deg"),
        _heading(grid, a, b),
        grid.vessel,
    )
    return components.total_mw


def solve_power_limited_speed(grid: PlanningGrid, a: Point, b: Point) -> float:
    vessel = grid.vessel
    if required_power_mw(grid, a, b, vessel.maximum_speed_kn) <= vessel.power_limit_mw:
        return vessel.maximum_speed_kn
    if required_power_mw(grid, a, b, vessel.search_min_speed_kn) > vessel.power_limit_mw:
        return math.inf
    lower, upper = vessel.search_min_speed_kn, vessel.maximum_speed_kn
    for _ in range(45):
        middle = (lower + upper) * 0.5
        if required_power_mw(grid, a, b, middle) <= vessel.power_limit_mw:
            lower = middle
        else:
            upper = middle
    return lower if lower >= vessel.operation_min_speed_kn else math.inf


def calculate_edge_transit(
    grid: PlanningGrid, a: Point, b: Point
) -> EdgeTransitResult:
    key = (a, b)
    cached = grid.edge_cache.get(key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    distance = grid.distance_km(a, b)
    risk = 0.5 * (float(grid.risk[a[1], a[0]]) + float(grid.risk[b[1], b[0]]))
    heading = _heading(grid, a, b)
    speed = solve_power_limited_speed(grid, a, b)
    current_along = (
        _midpoint(grid, a, b, "current_u_ms") * heading[0]
        + _midpoint(grid, a, b, "current_v_ms") * heading[1]
    ) / KN_TO_MPS
    ground_speed = speed + current_along if math.isfinite(speed) else math.inf
    components = (
        _power_components(
            _midpoint(grid, a, b, "ice_concentration"),
            _midpoint(grid, a, b, "ice_thickness_m"),
            speed,
            _midpoint(grid, a, b, "wind_u_ms"),
            _midpoint(grid, a, b, "wind_v_ms"),
            _midpoint(grid, a, b, "wave_height_m"),
            _midpoint(grid, a, b, "wave_direction_deg"),
            heading,
            grid.vessel,
        )
        if math.isfinite(speed)
        else None
    )
    feasible = math.isfinite(speed) and ground_speed > GROUND_MIN_SPEED_KN and components is not None
    if not feasible:
        result = EdgeTransitResult(
            False,
            risk,
            distance,
            speed,
            current_along,
            ground_speed,
            math.inf,
            math.inf,
            math.inf,
            math.inf,
            math.inf,
            math.inf,
            math.inf,
            False,
            grid.vessel.power_limit_mw,
            "power_or_ground_speed_infeasible",
        )
    else:
        time_h = distance / (KM_PER_NM * ground_speed)
        result = EdgeTransitResult(
            True,
            risk,
            distance,
            speed,
            current_along,
            ground_speed,
            components.calm_mw,
            components.ice_mw,
            components.wind_mw,
            components.wave_mw,
            components.total_mw,
            time_h,
            components.total_mw * time_h,
            speed < grid.vessel.maximum_speed_kn - 1e-3,
            grid.vessel.power_limit_mw,
            None,
        )
    grid.edge_cache[key] = result
    return result


def summarize_path_edges(grid: PlanningGrid, path: list[Point]) -> dict[str, object]:
    edges = [calculate_edge_transit(grid, a, b) for a, b in zip(path, path[1:], strict=False)]
    feasible = [edge for edge in edges if edge.feasible]
    if not feasible:
        return {
            "edgeCount": len(edges),
            "feasible": False,
            "meanSpeedThroughWaterKn": 0.0,
            "minSpeedThroughWaterKn": 0.0,
            "maxSpeedThroughWaterKn": 0.0,
            "meanSpeedOverGroundKn": 0.0,
            "meanPowerMw": 0.0,
            "maxPowerMw": 0.0,
            "maxPowerUtilization": 0.0,
            "powerLimitedEdges": 0,
        }
    speeds = [edge.speed_through_water_kn for edge in feasible]
    ground_speeds = [edge.speed_over_ground_kn for edge in feasible]
    powers = [edge.total_power_mw for edge in feasible]
    return {
        "edgeCount": len(edges),
        "feasible": len(feasible) == len(edges),
        "meanSpeedThroughWaterKn": sum(speeds) / len(speeds),
        "minSpeedThroughWaterKn": min(speeds),
        "maxSpeedThroughWaterKn": max(speeds),
        "meanSpeedOverGroundKn": sum(ground_speeds) / len(ground_speeds),
        "meanPowerMw": sum(powers) / len(powers),
        "maxPowerMw": max(powers),
        "maxPowerUtilization": max(powers) / grid.vessel.power_limit_mw,
        "powerLimitedEdges": sum(edge.power_limited for edge in feasible),
    }
