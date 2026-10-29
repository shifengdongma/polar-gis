"""Build a planning grid from the environment snapshot.

``real_only`` never synthesizes values: missing required fields become
obstacles/unknown and planning fails or returns no feasible route.
``allow_synthetic_research`` uses the reference V3 deterministic gap-fill and
marks every generated component as synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from math import atan2, ceil, cos, degrees, hypot, pi, radians, sin

import numpy as np

from app.navigation.contracts import DataQuality
from app.navigation.environment.models import FieldObservation
from app.navigation.environment.service import EnvironmentService
from app.navigation.risk.evaluator import RiskInput, RiskResult, evaluate_risk
from app.navigation.vessel.models import VesselProfile

from .errors import PlanningCancelled
from .grid import PlanningGrid
from .static_grid import StaticPlanningGrid

REQUIRED_FIELDS = ("bathymetry", "ice", "wind", "current", "wave")
GAP_FILL_SOURCE = "planner-deterministic-gap-fill-v1"


class EnvironmentDataMissing(RuntimeError):
    def __init__(self, message: str, fields: dict[str, int] | None = None) -> None:
        super().__init__(message)
        self.fields = fields or {}


@dataclass(slots=True)
class GridBuildResult:
    grid: PlanningGrid
    cells: list[dict[str, object]]
    static: StaticPlanningGrid
    requested_start: tuple[float, float]
    requested_goal: tuple[float, float]
    resolved_start: tuple[float, float]
    resolved_goal: tuple[float, float]
    resolved_start_cell: tuple[int, int]
    resolved_goal_cell: tuple[int, int]
    missing_by_field: dict[str, int] = field(default_factory=dict)


def build_planning_grid(
    static: StaticPlanningGrid,
    service: EnvironmentService,
    departure: datetime,
    vessel: VesselProfile,
    policy: str,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    start: tuple[float, float] | None = None,
    goal: tuple[float, float] | None = None,
    progress: Callable[[int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    synthetic_overrides: dict[str, float] | None = None,
) -> GridBuildResult:
    if policy not in {"real_only", "allow_synthetic_research"}:
        raise ValueError(f"Unsupported data policy: {policy}")
    indices = (
        static.viewport_indices(bbox)
        if bbox is not None
        else [
            (int(column), int(row))
            for row, column in zip(*np.where(static.inside_region), strict=True)
        ]
    )
    if not indices:
        raise EnvironmentDataMissing("No planning cells inside the requested region.")
    points = [static.cell_center(column, row) for column, row in indices]
    points_lonlat = [(longitude, latitude) for latitude, longitude in points]

    observations: dict[str, list[FieldObservation]] = {}
    for field_index, field_name in enumerate(REQUIRED_FIELDS):
        observations[field_name] = _sample_field_chunked(
            service,
            field_name,
            points_lonlat,
            departure,
            policy,
            progress,
            field_index,
            should_stop,
        )

    missing_by_field = {
        field: sum(1 for observation in observations[field] if not observation.available)
        for field in REQUIRED_FIELDS
    }
    if policy == "real_only":
        # The static grid depth is a real GEBCO-derived artifact, so a missing
        # live bathymetry provider does not invalidate the whole region.
        fatal = {
            field: count
            for field, count in missing_by_field.items()
            if field != "bathymetry" and count == len(indices)
        }
        if fatal:
            raise EnvironmentDataMissing(
                "Required environment fields are unavailable for the whole planning region.",
                fatal,
            )

    height, width = static.shape
    risk_array = np.ones((height, width), dtype=float)
    obstacle = ~static.static_traversable.copy()
    factors = {
        name: np.zeros((height, width), dtype=float)
        for name in ("ice", "depth", "fog", "wind", "wave")
    }
    metadata: dict[tuple[int, int], dict[str, object]] = {}
    cells: list[dict[str, object]] = []
    risk_version = "real_v1" if policy == "real_only" else "legacy_v1"
    day_of_year = departure.timetuple().tm_yday

    for index, (column, row) in enumerate(indices):
        if should_stop is not None and index % 200 == 0 and should_stop():
            raise PlanningCancelled("planning cancelled")
        if progress is not None and index and index % 2000 == 0:
            progress(55 + int(10 * index / len(indices)))
        latitude, longitude = points[index]
        field_obs = {field: observations[field][index] for field in REQUIRED_FIELDS}
        environment, quality, sources, missing = _cell_environment(
            field_obs,
            static,
            row,
            column,
            latitude,
            longitude,
            day_of_year,
            policy,
        )
        if policy == "allow_synthetic_research" and synthetic_overrides:
            _apply_synthetic_overrides(environment, quality, sources, synthetic_overrides)
        risk_input = RiskInput(
            latitude=latitude,
            longitude=longitude,
            day_of_year=day_of_year,
            depth_m=environment.get("depth_m"),
            ice_concentration=environment.get("ice_concentration"),
            ice_thickness_m=environment.get("ice_thickness_m"),
            wind_speed_ms=environment.get("wind_speed_ms"),
            wind_direction_from_deg=environment.get("wind_direction_deg"),
            wave_height_m=environment.get("wave_height_m"),
            wave_direction_from_deg=environment.get("wave_direction_deg"),
            current_u_ms=environment.get("current_u_ms"),
            current_v_ms=environment.get("current_v_ms"),
            quality=quality,
            sources=sources,
        )
        risk = evaluate_risk(risk_input, vessel, risk_version)  # type: ignore[arg-type]
        static_open = bool(static.static_traversable[row, column])
        blocked_reason = None
        if not static_open:
            blocked_reason = "land" if static.is_land[row, column] else "shallow_water"
        elif missing:
            blocked_reason = f"missing_environment:{','.join(missing)}"
        elif risk.traversable is not True:
            blocked_reason = risk.blocked_reason or "unknown_risk"
        traversable = static_open and not missing and risk.traversable is True
        obstacle[row, column] = not traversable
        combined = risk.combined_risk
        risk_array[row, column] = 1.0 if combined is None else combined
        for name, value in risk.components.items():
            factors[name][row, column] = 1.0 if value is None else value
        cell_metadata = {
            "environment": environment,
            "risk": {
                "ice": risk.ice_risk,
                "depth": risk.depth_risk,
                "fog": risk.fog_risk,
                "wind": risk.wind_risk,
                "wave": risk.wave_risk,
                "combined": risk.combined_risk,
            },
            "quality": _component_quality(risk),
            "sources": risk.sources,
            "traversable": traversable,
            "blockedReason": blocked_reason,
            "riskModelVersion": risk.model_version,
        }
        metadata[(column, row)] = cell_metadata
        cells.append(
            {
                "cellId": f"r{row}c{column}",
                "row": row,
                "column": column,
                "insidePlanningRegion": True,
                "center": {"latitude": latitude, "longitude": longitude},
                "bounds": static.cell_bounds(column, row),
                "geometry": static.cell_geometry(column, row),
                "cellSizeM": 25_000.0,
                "environment": environment,
                "risk": cell_metadata["risk"],
                "quality": cell_metadata["quality"],
                "sources": sources,
                "isLand": bool(static.is_land[row, column]),
                "landRatio": float(static.land_ratio[row, column]),
                "traversable": traversable,
                "blockedReason": blocked_reason,
                "riskModelVersion": risk.model_version,
            }
        )

    if start is None or goal is None:
        if start is not None or goal is not None:
            raise ValueError("Both start and goal are required.")
        resolved_start = _nearest_open(static, obstacle, (0, 0))
        resolved_goal = _nearest_open(static, obstacle, (static.width - 1, static.height - 1))
    else:
        requested_start_cell = static.nearest_cell(start[1], start[0])
        requested_goal_cell = static.nearest_cell(goal[1], goal[0])
        if requested_start_cell is None or requested_goal_cell is None:
            raise EnvironmentDataMissing("Start or goal is outside the NEP planning region.")
        resolved_start = _nearest_open(static, obstacle, requested_start_cell)
        resolved_goal = _nearest_open(static, obstacle, requested_goal_cell)
    if resolved_start is None or resolved_goal is None:
        raise EnvironmentDataMissing("No traversable start or goal cell exists.")

    start_lat, start_lon = static.cell_center(*resolved_start)
    goal_lat, goal_lon = static.cell_center(*resolved_goal)
    requested_start = start or (start_lon, start_lat)
    requested_goal = goal or (goal_lon, goal_lat)
    grid = PlanningGrid(
        latitudes=static.center_lat,
        longitudes=static.center_lon,
        risk=risk_array,
        obstacle=obstacle,
        factors=factors,
        cell_metadata=metadata,
        start=resolved_start,
        goal=resolved_goal,
        vessel=vessel,
        cell_size_m=25_000.0,
    )
    if progress is not None:
        progress(60)
    return GridBuildResult(
        grid=grid,
        cells=cells,
        static=static,
        requested_start=requested_start,
        requested_goal=requested_goal,
        resolved_start=(start_lon, start_lat),
        resolved_goal=(goal_lon, goal_lat),
        resolved_start_cell=resolved_start,
        resolved_goal_cell=resolved_goal,
        missing_by_field=missing_by_field,
    )


def _cell_environment(
    observations: dict[str, FieldObservation],
    static: StaticPlanningGrid,
    row: int,
    column: int,
    latitude: float,
    longitude: float,
    day_of_year: int,
    policy: str,
) -> tuple[dict[str, float | None], dict[str, str], dict[str, str], list[str]]:
    quality: dict[str, str] = {}
    sources: dict[str, str] = {}
    missing: list[str] = []

    depth = _value(observations["bathymetry"], "depthM")
    if depth is None:
        depth = float(static.depth_m[row, column])
        if depth > 0.0:
            quality["depth"] = DataQuality.REAL.value
            sources["depth"] = "static-grid"
    else:
        quality["depth"] = observations["bathymetry"].quality.value
        sources["depth"] = observations["bathymetry"].source or "unknown"

    ice_values = observations["ice"]
    concentration = _value(ice_values, "concentration")
    thickness = _value(ice_values, "thicknessM")
    if concentration is not None:
        quality["ice"] = ice_values.quality.value
        sources["ice"] = ice_values.source or "unknown"
    if policy == "allow_synthetic_research":
        if depth is None or depth <= 0.0:
            depth = synthetic_depth(latitude, longitude)
            if depth > 0.0:
                quality["depth"] = DataQuality.SYNTHETIC.value
                sources["depth"] = GAP_FILL_SOURCE
        if concentration is None or thickness is None:
            synthetic_concentration, synthetic_thickness = synthetic_ice(latitude, longitude, day_of_year)
            concentration = concentration if concentration is not None else synthetic_concentration
            thickness = thickness if thickness is not None else synthetic_thickness
            quality["ice"] = DataQuality.SYNTHETIC.value
            sources["ice"] = GAP_FILL_SOURCE
        allow_synthetic = True
    else:
        allow_synthetic = False
    wind = _wind_values(observations["wind"], latitude, longitude, day_of_year, allow_synthetic)
    current = _current_values(observations["current"], latitude, longitude, day_of_year, allow_synthetic)
    wave = _wave_values(observations["wave"], latitude, longitude, day_of_year, allow_synthetic)

    for field_name, values in (("wind", wind), ("current", current), ("wave", wave)):
        observation = observations[field_name]
        if values["missing"]:
            if allow_synthetic:
                quality[field_name] = DataQuality.SYNTHETIC.value
                sources[field_name] = GAP_FILL_SOURCE
            else:
                quality[field_name] = DataQuality.MISSING.value
                sources[field_name] = observation.source or "unknown"
                missing.append(field_name)
        else:
            quality[field_name] = observation.quality.value
            sources[field_name] = observation.source or "unknown"

    if depth is None:
        missing.append("bathymetry")
        quality["depth"] = DataQuality.MISSING.value
    if concentration is None or thickness is None:
        missing.append("ice")
        quality["ice"] = DataQuality.MISSING.value

    environment = {
        "depth_m": depth,
        "ice_concentration": concentration,
        "ice_thickness_m": thickness,
        "wind_speed_ms": wind["speed"],
        "wind_direction_deg": wind["direction"],
        "wind_u_ms": wind["u"],
        "wind_v_ms": wind["v"],
        "current_u_ms": current["u"],
        "current_v_ms": current["v"],
        "current_speed_ms": current["speed"],
        "wave_height_m": wave["height"],
        "wave_period_s": wave["period"],
        "wave_direction_deg": wave["direction"],
    }
    return environment, quality, sources, sorted(set(missing))


def _value(observation: FieldObservation, key: str) -> float | None:
    value = observation.values.get(key)
    return float(value) if isinstance(value, (int, float)) and np.isfinite(value) else None


def _wind_values(
    observation: FieldObservation,
    latitude: float,
    longitude: float,
    day_of_year: int,
    allow_synthetic: bool,
) -> dict[str, float | bool | None]:
    speed = _value(observation, "speedMs")
    u = _value(observation, "uMs")
    v = _value(observation, "vMs")
    direction = _value(observation, "directionFromDeg")
    if speed is None or u is None or v is None:
        if not allow_synthetic:
            return {"speed": None, "direction": None, "u": None, "v": None, "missing": True}
        speed, direction, u, v = synthetic_wind(latitude, longitude, day_of_year)
        return {"speed": speed, "direction": direction, "u": u, "v": v, "missing": False}
    return {"speed": speed, "direction": direction, "u": u, "v": v, "missing": False}


def _current_values(
    observation: FieldObservation,
    latitude: float,
    longitude: float,
    day_of_year: int,
    allow_synthetic: bool,
) -> dict[str, float | bool | None]:
    u = _value(observation, "uMs")
    v = _value(observation, "vMs")
    if u is None or v is None:
        if not allow_synthetic:
            return {"u": None, "v": None, "speed": None, "missing": True}
        phase = phase_radians(latitude, longitude, day_of_year)
        u, v = 0.35 * sin(phase), 0.35 * cos(phase)
        return {"u": u, "v": v, "speed": (u * u + v * v) ** 0.5, "missing": False}
    return {"u": u, "v": v, "speed": (u * u + v * v) ** 0.5, "missing": False}


def _wave_values(
    observation: FieldObservation,
    latitude: float,
    longitude: float,
    day_of_year: int,
    allow_synthetic: bool,
) -> dict[str, float | bool | None]:
    height = _value(observation, "heightM")
    period = _value(observation, "periodS")
    direction = _value(observation, "directionFromDeg")
    if height is None or period is None or direction is None:
        if not allow_synthetic:
            return {"height": None, "period": None, "direction": None, "missing": True}
        height, period, direction = synthetic_wave(latitude, longitude, day_of_year)
        return {"height": height, "period": period, "direction": direction, "missing": False}
    return {"height": height, "period": period, "direction": direction, "missing": False}


def _sample_field_chunked(
    service: EnvironmentService,
    field: str,
    points: list[tuple[float, float]],
    departure: datetime,
    policy: str,
    progress: Callable[[int], None] | None,
    field_index: int,
    should_stop: Callable[[], bool] | None,
) -> list[FieldObservation]:
    """Sample one provider in bounded chunks so progress is visible.

    A single 15k-point call used to leave the UI at the initial 10% for the
    whole provider read.  Chunking updates the run progress (and checks
    cancellation) between chunks while keeping one provider handle warm.
    """
    chunk_size = 1000
    chunks = max(1, ceil(len(points) / chunk_size))
    result: list[FieldObservation] = []
    for chunk_index in range(chunks):
        if should_stop is not None and should_stop():
            raise PlanningCancelled("planning cancelled")
        start = chunk_index * chunk_size
        end = min(len(points), start + chunk_size)
        result.extend(service.sample_many(field, points[start:end], departure, policy))
        if progress is not None:
            fraction = (field_index + (chunk_index + 1) / chunks) / len(REQUIRED_FIELDS)
            progress(10 + int(45 * fraction))
    return result


def _apply_synthetic_overrides(
    environment: dict[str, float | None],
    quality: dict[str, str],
    sources: dict[str, str],
    overrides: dict[str, float],
) -> None:
    """Apply explicit research overrides to every cell.

    Values remain synthetic; the caller/UI must display the override source.
    """
    if "depthM" in overrides:
        environment["depth_m"] = float(overrides["depthM"])
        quality["depth"] = DataQuality.SYNTHETIC.value
        sources["depth"] = "research-override"
    if any(key in overrides for key in ("iceConcentration", "iceThicknessM")):
        if "iceConcentration" in overrides:
            environment["ice_concentration"] = float(overrides["iceConcentration"])
        if "iceThicknessM" in overrides:
            environment["ice_thickness_m"] = float(overrides["iceThicknessM"])
        quality["ice"] = DataQuality.SYNTHETIC.value
        sources["ice"] = "research-override"
    if any(key in overrides for key in ("windSpeedMs", "windDirectionFromDeg")):
        speed = float(overrides.get("windSpeedMs", environment.get("wind_speed_ms") or 0.0))
        direction = float(
            overrides.get("windDirectionFromDeg", environment.get("wind_direction_deg") or 0.0)
        )
        radians_direction = radians(direction)
        environment["wind_speed_ms"] = speed
        environment["wind_direction_deg"] = direction
        environment["wind_u_ms"] = -speed * sin(radians_direction)
        environment["wind_v_ms"] = -speed * cos(radians_direction)
        quality["wind"] = DataQuality.SYNTHETIC.value
        sources["wind"] = "research-override"
    if any(key in overrides for key in ("currentSpeedMs", "currentDirectionToDeg")):
        speed = float(overrides.get("currentSpeedMs", environment.get("current_speed_ms") or 0.0))
        if "currentDirectionToDeg" in overrides:
            direction = float(overrides["currentDirectionToDeg"])
        else:
            existing_u = float(environment.get("current_u_ms") or 0.0)
            existing_v = float(environment.get("current_v_ms") or 0.0)
            direction = (
                degrees(atan2(existing_u, existing_v))
                if hypot(existing_u, existing_v) > 0
                else 0.0
            )
        radians_direction = radians(direction)
        environment["current_speed_ms"] = speed
        environment["current_u_ms"] = speed * sin(radians_direction)
        environment["current_v_ms"] = speed * cos(radians_direction)
        quality["current"] = DataQuality.SYNTHETIC.value
        sources["current"] = "research-override"
    if any(key in overrides for key in ("waveHeightM", "wavePeriodS", "waveDirectionFromDeg")):
        if "waveHeightM" in overrides:
            environment["wave_height_m"] = float(overrides["waveHeightM"])
        if "wavePeriodS" in overrides:
            environment["wave_period_s"] = float(overrides["wavePeriodS"])
        if "waveDirectionFromDeg" in overrides:
            environment["wave_direction_deg"] = float(overrides["waveDirectionFromDeg"])
        quality["wave"] = DataQuality.SYNTHETIC.value
        sources["wave"] = "research-override"


def _component_quality(risk: RiskResult) -> dict[str, str]:
    quality = dict(risk.quality)
    for name, value in risk.components.items():
        quality[name] = quality.get(name, DataQuality.MISSING.value if value is None else DataQuality.REAL.value)
        if value is None and quality.get(name) != DataQuality.SYNTHETIC.value:
            quality[name] = DataQuality.MISSING.value
    quality["combined"] = risk.combined_quality
    return quality


def _nearest_open(
    static: StaticPlanningGrid,
    obstacle: np.ndarray,
    requested: tuple[int, int],
) -> tuple[int, int] | None:
    width, height = static.width, static.height
    x, y = requested
    for radius in range(max(width, height)):
        for yy in range(max(0, y - radius), min(height, y + radius + 1)):
            for xx in range(max(0, x - radius), min(width, x + radius + 1)):
                if max(abs(xx - x), abs(yy - y)) != radius:
                    continue
                if static.inside_region[yy, xx] and not obstacle[yy, xx]:
                    return xx, yy
    return None


def phase_radians(latitude: float, longitude: float, day_of_year: int) -> float:
    return radians(latitude * 2.7 + longitude * 0.83 + day_of_year * 3.1)


def synthetic_depth(latitude: float, longitude: float) -> float:
    p = radians(latitude * 1.9 + longitude * 0.55)
    q = radians(latitude * 0.43 - longitude * 1.15)
    continental = sin(p) + 0.55 * sin(q) + 0.2 * cos(0.43 * p)
    if continental > 1.0:
        return 0.0
    return 1800.0 + 1800.0 * (0.5 + 0.5 * sin(p + q))


def synthetic_ice(latitude: float, longitude: float, day_of_year: int) -> tuple[float, float]:
    seasonal = 0.5 + 0.5 * cos(radians(day_of_year - 35))
    polar = min(1.0, max(0.0, (abs(latitude) - 52.0) / 35.0))
    wave = 0.5 + 0.5 * sin(radians(longitude * 2.0 + latitude * 3.0))
    concentration = min(1.0, max(0.0, polar * (0.18 + 0.65 * seasonal) * (0.65 + 0.35 * wave)))
    thickness = min(2.2, max(0.0, concentration * (0.25 + 1.25 * seasonal)))
    return concentration, thickness


def synthetic_wind(
    latitude: float, longitude: float, day_of_year: int
) -> tuple[float, float, float, float]:
    phase = phase_radians(latitude, longitude, day_of_year)
    speed = min(22.0, max(0.5, 6.0 + 5.0 * sin(phase) + 2.5 * cos(0.61 * phase)))
    direction = (180.0 + (1.7 * phase * 180.0 / pi)) % 360.0
    radians_direction = radians(direction)
    u = -speed * sin(radians_direction)
    v = -speed * cos(radians_direction)
    return speed, direction, u, v


def synthetic_wave(
    latitude: float, longitude: float, day_of_year: int
) -> tuple[float, float, float]:
    phase = phase_radians(latitude, longitude, day_of_year)
    height = min(7.5, max(0.1, 1.4 + 1.8 * (0.5 + 0.5 * sin(1.31 * phase)) + 0.7 * abs(sin(0.47 * phase))))
    period = min(14.0, max(3.0, 6.0 + 2.5 * cos(phase)))
    direction = ((2.0 * phase * 180.0 / pi) + 180.0) % 360.0
    return height, period, direction
