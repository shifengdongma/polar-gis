"""Planning orchestration: environment snapshot → risk grid → D*/NSGA-III."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from math import asin, ceil, cos, radians, sin, sqrt
from time import perf_counter
from uuid import uuid4

import numpy as np

from app.navigation.contracts import DataQuality, ensure_utc
from app.navigation.environment.service import EnvironmentService
from app.navigation.vessel.models import VesselProfile
from app.navigation.vessel.service import VesselService

from .dnsga3 import Individual, NoFeasibleRoute, representative_routes, run_nsga3
from .energy_model import EdgeTransitResult, calculate_edge_transit, summarize_path_edges
from .environment_adapter import EnvironmentDataMissing, GridBuildResult, build_planning_grid
from .errors import PlanningCancelled, PlanningTimeout
from .grid import PlanningGrid, Point
from .static_grid import StaticPlanningGrid, load_static_grid

ALGORITHM_VERSION = "dnsga3-v3-port-1"


@dataclass(frozen=True)
class PlanningRequest:
    start_longitude: float
    start_latitude: float
    goal_longitude: float
    goal_latitude: float
    departure: datetime
    vessel_id: str
    data_policy: str
    population_size: int = 36
    generations: int = 20
    seed: int = 42
    bbox: tuple[float, float, float, float] | None = None
    synthetic_overrides: dict[str, float] | None = None


@dataclass
class PlanningOutcome:
    routes: list[dict[str, object]]
    risk_grid: dict[str, object]
    snapshot: dict[str, object]
    requested_start: tuple[float, float]
    requested_goal: tuple[float, float]
    resolved_start: tuple[float, float]
    resolved_goal: tuple[float, float]
    missing_by_field: dict[str, int]
    algorithm_version: str
    elapsed_seconds: float
    build: GridBuildResult
    no_route_reason: str | None = None


class PlannerService:
    def __init__(
        self,
        environment_service: EnvironmentService,
        vessel_service: VesselService | None = None,
        static_grid: StaticPlanningGrid | None = None,
    ) -> None:
        self.environment_service = environment_service
        self.vessel_service = vessel_service or VesselService()
        self.static_grid = static_grid or load_static_grid()

    def plan(
        self,
        request: PlanningRequest,
        *,
        progress: Callable[[int], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        deadline: float | None = None,
    ) -> PlanningOutcome:
        started = perf_counter()
        vessel = self.vessel_service.get(request.vessel_id)
        departure = ensure_utc(request.departure)
        if progress is not None:
            progress(2)
        snapshot = self.environment_service.snapshot(departure, request.data_policy)
        if progress is not None:
            progress(5)
        checker = _stop_checker(should_stop, deadline)
        try:
            build = build_planning_grid(
                self.static_grid,
                self.environment_service,
                departure,
                vessel,
                request.data_policy,
                start=(request.start_longitude, request.start_latitude),
                goal=(request.goal_longitude, request.goal_latitude),
                progress=progress,
                should_stop=checker,
                synthetic_overrides=request.synthetic_overrides,
            )
            if progress is not None:
                progress(65)
            try:
                front = run_nsga3(
                    build.grid,
                    population_size=request.population_size,
                    generations=request.generations,
                    seed=request.seed,
                    should_stop=checker,
                )
            except NoFeasibleRoute as error:
                # Keep the risk grid for analysis even when no route exists.
                return PlanningOutcome(
                    routes=[],
                    risk_grid=self._risk_grid_payload(build),
                    snapshot=_snapshot_payload(snapshot, request),
                    requested_start=(request.start_longitude, request.start_latitude),
                    requested_goal=(request.goal_longitude, request.goal_latitude),
                    resolved_start=build.resolved_start,
                    resolved_goal=build.resolved_goal,
                    missing_by_field=build.missing_by_field,
                    algorithm_version=ALGORITHM_VERSION,
                    elapsed_seconds=perf_counter() - started,
                    build=build,
                    no_route_reason=str(error),
                )
            if not front:
                raise NoFeasibleRoute("No non-dominated route was produced.")
            representatives = representative_routes(front)
            recommended = representatives.get("lowest_risk")
            routes = self._routes(build, front, representatives)
            risk_grid = self._risk_grid_payload(build)
            if progress is not None:
                progress(95)
        except (EnvironmentDataMissing, NoFeasibleRoute, PlanningCancelled, PlanningTimeout):
            raise
        except Exception as error:  # noqa: BLE001 - processor maps this to failed
            raise RuntimeError(f"planner failed: {error}") from error
        if recommended is None:
            raise NoFeasibleRoute("No recommended route was produced.")
        return PlanningOutcome(
            routes=routes,
            risk_grid=risk_grid,
            snapshot=_snapshot_payload(snapshot, request),
            requested_start=(request.start_longitude, request.start_latitude),
            requested_goal=(request.goal_longitude, request.goal_latitude),
            resolved_start=build.resolved_start,
            resolved_goal=build.resolved_goal,
            missing_by_field=build.missing_by_field,
            algorithm_version=ALGORITHM_VERSION,
            elapsed_seconds=perf_counter() - started,
            build=build,
        )

    def risk_only(
        self,
        request: PlanningRequest,
        *,
        progress: Callable[[int], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        deadline: float | None = None,
    ) -> PlanningOutcome:
        """Build a risk grid without running D* Lite/NSGA-III."""
        started = perf_counter()
        vessel = self.vessel_service.get(request.vessel_id)
        departure = ensure_utc(request.departure)
        if progress is not None:
            progress(2)
        snapshot = self.environment_service.snapshot(departure, request.data_policy)
        checker = _stop_checker(should_stop, deadline)
        build = build_planning_grid(
            self.static_grid,
            self.environment_service,
            departure,
            vessel,
            request.data_policy,
            bbox=request.bbox,
            start=(request.start_longitude, request.start_latitude),
            goal=(request.goal_longitude, request.goal_latitude),
            progress=progress,
            should_stop=checker,
            synthetic_overrides=request.synthetic_overrides,
        )
        return PlanningOutcome(
            routes=[],
            risk_grid=self._risk_grid_payload(build),
            snapshot=_snapshot_payload(snapshot, request),
            requested_start=(request.start_longitude, request.start_latitude),
            requested_goal=(request.goal_longitude, request.goal_latitude),
            resolved_start=build.resolved_start,
            resolved_goal=build.resolved_goal,
            missing_by_field=build.missing_by_field,
            algorithm_version=ALGORITHM_VERSION,
            elapsed_seconds=perf_counter() - started,
            build=build,
        )

    def _routes(
        self,
        build: GridBuildResult,
        front: list[Individual],
        representatives: dict[str, Individual],
    ) -> list[dict[str, object]]:
        labels: dict[tuple[Point, ...], str] = {
            tuple(item.path): label for label, item in representatives.items()
        }
        recommended_path = tuple(representatives["lowest_risk"].path)
        routes: list[dict[str, object]] = []
        for index, item in enumerate(front):
            coordinates = [
                [float(build.grid.coordinate(point)[1]), float(build.grid.coordinate(point)[0])]
                for point in item.path
            ]
            components = _path_risk_components(build.grid, item.path)
            quality = _path_quality(build.grid, item.path)
            routes.append(
                {
                    "routeIndex": index,
                    "routeId": uuid4().hex,
                    "label": _route_label(labels.get(tuple(item.path)), index),
                    "recommended": tuple(item.path) == recommended_path,
                    "coordinates": coordinates,
                    "cellIds": [f"r{point[1]}c{point[0]}" for point in item.path],
                    "riskScore": float(item.objectives[0]),
                    "riskComponents": components,
                    "energyMWh": float(item.objectives[1]),
                    "timeHours": float(item.objectives[2]),
                    "distanceKm": _path_distance(build.grid, item.path),
                    "sourceQuality": quality,
                    "algorithmVersion": ALGORITHM_VERSION,
                    "edgeDiagnostics": summarize_path_edges(build.grid, item.path),
                }
            )
        return routes

    def _risk_grid_payload(self, build: GridBuildResult) -> dict[str, object]:
        return {
            "width": build.grid.width,
            "height": build.grid.height,
            "cellSizeM": build.grid.cell_size_m,
            "coordinateReference": "EPSG:3413 fixed 25 km grid; cell centres WGS84",
            "cells": build.cells,
        }

    def evaluate_route(
        self,
        risk_grid: dict[str, object],
        coordinates: list[tuple[float, float]],
        vessel: VesselProfile,
    ) -> dict[str, object]:
        """Re-evaluate an adopted route against a stored risk-grid snapshot."""
        if len(coordinates) < 2:
            return {"traversable": False, "reason": "route_requires_two_points"}
        cells = {
            str(cell["cellId"]): cell
            for cell in risk_grid.get("cells", [])
            if isinstance(cell, dict) and "cellId" in cell
        }
        sampled = _densified_cells(self.static_grid, coordinates, cells)
        if isinstance(sampled, str):
            return {"traversable": False, "reason": sampled}
        results: list[EdgeTransitResult] = []
        risk_total = 0.0
        energy_total = 0.0
        time_total = 0.0
        distance_total = 0.0
        for first_id, second_id in zip(sampled, sampled[1:], strict=False):
            first = cells[first_id]
            second = cells[second_id]
            grid = _two_cell_grid(first, second, vessel)
            result = calculate_edge_transit(grid, (0, 0), (1, 0))
            if not result.feasible:
                return {
                    "traversable": False,
                    "reason": result.reason or "edge_infeasible",
                    "blockedCellId": second_id,
                }
            results.append(result)
            risk_total += result.risk
            energy_total += result.energy_mwh
            time_total += result.travel_time_h
            distance_total += result.distance_km
        qualities = [
            str(cells[cell_id].get("quality", {}).get("combined", "unknown"))
            for cell_id in sampled
        ]
        return {
            "traversable": True,
            "riskScore": risk_total,
            "energyMWh": energy_total,
            "timeHours": time_total,
            "distanceKm": distance_total,
            "sourceQuality": _aggregate_quality(qualities),
            "cellIds": sampled,
            "snapshotId": risk_grid.get("snapshotId"),
        }


def _snapshot_payload(snapshot, request: PlanningRequest) -> dict[str, object]:
    payload = snapshot.model_dump(mode="json")
    payload["syntheticOverrides"] = request.synthetic_overrides or {}
    return payload


def _stop_checker(
    should_stop: Callable[[], bool] | None,
    deadline: float | None,
) -> Callable[[], bool]:
    def check() -> bool:
        if should_stop is not None and should_stop():
            return True
        if deadline is not None and perf_counter() >= deadline:
            raise PlanningTimeout("planning deadline exceeded")
        return False

    return check


def _route_label(name: str | None, index: int) -> str:
    return {
        "lowest_risk": "最低风险",
        "lowest_energy": "最低能耗",
        "fastest_time": "最短航时",
    }.get(name or "", f"候选航线 {index + 1}")


def _path_risk_components(grid: PlanningGrid, path: list[Point]) -> dict[str, float | None]:
    components = {"ice": [], "depth": [], "fog": [], "wind": [], "wave": []}
    for point in path:
        cell = grid.cell_metadata.get(point, {})
        risk = cell.get("risk", {}) if isinstance(cell, dict) else {}
        if isinstance(risk, dict):
            for name in components:
                value = risk.get(name)
                if isinstance(value, (int, float)):
                    components[name].append(float(value))
    return {
        name: (sum(values) / len(values) if values else None)
        for name, values in components.items()
    } | {"combined": float(np.mean([grid.risk[point[1], point[0]] for point in path]))}


def _path_quality(grid: PlanningGrid, path: list[Point]) -> str:
    values: list[str] = []
    for point in path:
        cell = grid.cell_metadata.get(point, {})
        quality = cell.get("quality", {}) if isinstance(cell, dict) else {}
        values.append(str(quality.get("combined", "unknown")))
    return _aggregate_quality(values)


def _aggregate_quality(values: list[str]) -> str:
    if not values:
        return DataQuality.UNKNOWN.value
    if any(value in {"missing", "unknown"} for value in values):
        return DataQuality.UNKNOWN.value
    if any(value == "synthetic" for value in values):
        return DataQuality.SYNTHETIC.value
    return DataQuality.REAL.value


def _path_distance(grid: PlanningGrid, path: list[Point]) -> float:
    return sum(grid.distance_km(a, b) for a, b in zip(path, path[1:], strict=False))


def _two_cell_grid(first: dict[str, object], second: dict[str, object], vessel: VesselProfile) -> PlanningGrid:
    first_center = first["center"]
    second_center = second["center"]
    assert isinstance(first_center, dict) and isinstance(second_center, dict)
    return PlanningGrid(
        latitudes=np.array([[float(first_center["latitude"]), float(second_center["latitude"])]]),
        longitudes=np.array([[float(first_center["longitude"]), float(second_center["longitude"])]]),
        risk=np.array(
            [
                [
                    float(first.get("risk", {}).get("combined", 1.0)),  # type: ignore[union-attr]
                    float(second.get("risk", {}).get("combined", 1.0)),  # type: ignore[union-attr]
                ]
            ]
        ),
        obstacle=np.zeros((1, 2), dtype=bool),
        factors={},
        cell_metadata={
            (0, 0): {"environment": first.get("environment", {})},
            (1, 0): {"environment": second.get("environment", {})},
        },
        start=(0, 0),
        goal=(1, 0),
        vessel=vessel,
    )


def _densified_cells(
    static: StaticPlanningGrid,
    coordinates: list[tuple[float, float]],
    cells: dict[str, dict[str, object]],
) -> list[str] | str:
    """Map a WGS84 route to planning cells.

    For a candidate route produced by the planner, consecutive coordinates are
    adjacent cell centres; using them directly preserves the exact edge energy
    used by the optimizer.  Only long user-edited segments are densified.
    """
    ids: list[str] = []
    for first, second in zip(coordinates, coordinates[1:], strict=False):
        first_point = static.nearest_cell(first[1], first[0])
        second_point = static.nearest_cell(second[1], second[0])
        if first_point is None or second_point is None:
            return "route_outside_planning_region"
        first_id = f"r{first_point[1]}c{first_point[0]}"
        second_id = f"r{second_point[1]}c{second_point[0]}"
        if not _cell_in_grid(first_id, cells):
            return _cell_error(first_id, cells)
        if not _cell_in_grid(second_id, cells):
            return _cell_error(second_id, cells)
        if not ids:
            ids.append(first_id)
        if first_id == second_id:
            continue
        if _adjacent_cells(first_point, second_point):
            if ids[-1] != second_id:
                ids.append(second_id)
            continue
        for longitude, latitude in _densify(first, second, 5.0):
            point = static.nearest_cell(latitude, longitude)
            if point is None:
                return "route_outside_planning_region"
            cell_id = f"r{point[1]}c{point[0]}"
            if not _cell_in_grid(cell_id, cells):
                return _cell_error(cell_id, cells)
            if ids[-1] != cell_id:
                ids.append(cell_id)
    return ids


def _cell_in_grid(cell_id: str, cells: dict[str, dict[str, object]]) -> bool:
    cell = cells.get(cell_id)
    return cell is not None and cell.get("traversable") is True


def _cell_error(cell_id: str, cells: dict[str, dict[str, object]]) -> str:
    cell = cells.get(cell_id)
    if cell is None:
        return "risk_grid_cell_unavailable"
    return str(cell.get("blockedReason") or "cell_not_traversable")


def _adjacent_cells(first: tuple[int, int], second: tuple[int, int]) -> bool:
    return max(abs(first[0] - second[0]), abs(first[1] - second[1])) <= 1


def _densify(first: tuple[float, float], second: tuple[float, float], step_km: float) -> list[tuple[float, float]]:
    lon1, lat1 = first
    lon2, lat2 = second
    distance = _great_circle_km(first, second)
    count = max(1, int(ceil(distance / step_km)))
    lon_delta = (lon2 - lon1 + 180.0) % 360.0 - 180.0
    return [
        (
            (lon1 + lon_delta * index / count + 180.0) % 360.0 - 180.0,
            lat1 + (lat2 - lat1) * index / count,
        )
        for index in range(count + 1)
    ]


def _great_circle_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    lon1, lat1 = map(radians, first)
    lon2, lat2 = map(radians, second)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    hav = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371.0088 * 2 * asin(min(1.0, sqrt(hav)))
