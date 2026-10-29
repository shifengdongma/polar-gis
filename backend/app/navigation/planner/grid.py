"""Search grid over the fixed 25 km planning cells."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt

import numpy as np

from app.navigation.vessel.models import VesselProfile

Point = tuple[int, int]


@dataclass(slots=True)
class PlanningGrid:
    latitudes: np.ndarray
    longitudes: np.ndarray
    risk: np.ndarray
    obstacle: np.ndarray
    factors: dict[str, np.ndarray]
    cell_metadata: dict[Point, dict[str, object]]
    start: Point
    goal: Point
    vessel: VesselProfile
    cell_size_m: float = 25_000.0
    edge_cache: dict[tuple[Point, Point], object] = field(default_factory=dict)

    @property
    def width(self) -> int:
        return int(self.risk.shape[1])

    @property
    def height(self) -> int:
        return int(self.risk.shape[0])

    def in_bounds(self, point: Point) -> bool:
        x, y = point
        return 0 <= x < self.width and 0 <= y < self.height

    def traversable(self, point: Point) -> bool:
        return self.in_bounds(point) and not bool(self.obstacle[point[1], point[0]])

    def coordinate(self, point: Point) -> tuple[float, float]:
        x, y = point
        return float(self.latitudes[y, x]), float(self.longitudes[y, x])

    def neighbors(self, point: Point) -> Iterable[Point]:
        x, y = point
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            candidate = (x + dx, y + dy)
            if not self.traversable(candidate):
                continue
            if dx and dy and (
                not self.traversable((x + dx, y)) or not self.traversable((x, y + dy))
            ):
                continue
            yield candidate

    def distance_km(self, a: Point, b: Point) -> float:
        lat1_deg, lon1_deg = self.coordinate(a)
        lat2_deg, lon2_deg = self.coordinate(b)
        lat1 = radians(lat1_deg)
        lat2 = radians(lat2_deg)
        dlat = lat2 - lat1
        dlon = radians((lon2_deg - lon1_deg + 180.0) % 360.0 - 180.0)
        hav = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        return 6371.0088 * 2 * asin(min(1.0, sqrt(hav)))

    def edge_result(self, a: Point, b: Point):
        from .energy_model import calculate_edge_transit

        return calculate_edge_transit(self, a, b)

    def edge(self, a: Point, b: Point) -> tuple[float, float, float]:
        result = self.edge_result(a, b)
        return result.risk, result.energy_mwh, result.travel_time_h
