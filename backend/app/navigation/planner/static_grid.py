"""Fixed 25 km Northeast Passage planning grid loaded from the V3 NPZ artifact.

This is a business grid in EPSG:3413, not a map tile, screen pixel, or
OpenLayers zoom level.  Cell centres are WGS84 for API/business use.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

GRID_CRS = "EPSG:3413"
STATIC_GRID_VERSION = 3
_GRID_PATH = (
    Path(__file__).resolve().parents[1]
    / "resources"
    / "grids"
    / "northeast_passage_25km_static.npz"
)


class PlanningGridUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class StaticPlanningGrid:
    metadata: dict[str, object]
    center_lat: np.ndarray
    center_lon: np.ndarray
    corners_lat: np.ndarray
    corners_lon: np.ndarray
    inside_region: np.ndarray
    is_land: np.ndarray
    land_ratio: np.ndarray
    depth_m: np.ndarray
    static_traversable: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        return self.center_lat.shape

    @property
    def height(self) -> int:
        return int(self.shape[0])

    @property
    def width(self) -> int:
        return int(self.shape[1])

    def contains(self, latitude: float, longitude: float) -> bool:
        region = self.metadata["region"]
        planning_lon = longitude + 360.0 if longitude < 0.0 else longitude
        return (
            float(region["south"]) <= latitude <= float(region["north"])
            and float(region["planning_west"]) <= planning_lon <= float(region["planning_east"])
        )

    def nearest_cell(self, latitude: float, longitude: float) -> tuple[int, int] | None:
        if not self.contains(latitude, longitude):
            return None
        delta = ((self.center_lon - longitude + 180.0) % 360.0) - 180.0
        distance = (self.center_lat - latitude) ** 2 + (
            delta * np.cos(np.radians(latitude))
        ) ** 2
        distance = np.where(self.inside_region, distance, np.inf)
        row, column = np.unravel_index(np.argmin(distance), distance.shape)
        return int(column), int(row)

    def cell_center(self, column: int, row: int) -> tuple[float, float]:
        """Return ``(latitude, longitude)`` for a cell."""
        return float(self.center_lat[row, column]), float(self.center_lon[row, column])

    def cell_bounds(self, column: int, row: int) -> dict[str, float]:
        return {
            "north": float(self.corners_lat[row, column].max()),
            "south": float(self.corners_lat[row, column].min()),
            "east": float(self.corners_lon[row, column].max()),
            "west": float(self.corners_lon[row, column].min()),
        }

    def cell_geometry(self, column: int, row: int) -> list[list[float]]:
        return [
            [float(self.corners_lon[row, column, index]), float(self.corners_lat[row, column, index])]
            for index in range(4)
        ]

    def viewport_indices(
        self, bbox: tuple[float, float, float, float]
    ) -> list[tuple[int, int]]:
        """Return inside-region cells intersecting a WGS84 bbox."""
        west, south, east, north = bbox
        if west <= east:
            lon_ok = (self.center_lon >= west) & (self.center_lon <= east)
        else:
            lon_ok = (self.center_lon >= west) | (self.center_lon <= east)
        mask = (
            self.inside_region
            & (self.center_lat >= south)
            & (self.center_lat <= north)
            & lon_ok
        )
        rows, columns = np.where(mask)
        return [(int(column), int(row)) for row, column in zip(rows, columns, strict=True)]


@lru_cache
def load_static_grid(path: Path | None = None) -> StaticPlanningGrid:
    artifact = path or _GRID_PATH
    if not artifact.is_file():
        raise PlanningGridUnavailable(f"Planning grid artifact is missing: {artifact}")
    with np.load(artifact, allow_pickle=False) as value:
        try:
            metadata = json.loads(str(value["metadata"]))
        except (KeyError, ValueError) as error:
            raise PlanningGridUnavailable("Planning grid metadata is invalid.") from error
        if metadata.get("version") != STATIC_GRID_VERSION:
            raise PlanningGridUnavailable(
                f"Planning grid version {metadata.get('version')} is not supported."
            )
        return StaticPlanningGrid(
            metadata=metadata,
            center_lat=np.asarray(value["center_lat"], dtype=np.float64),
            center_lon=np.asarray(value["center_lon"], dtype=np.float64),
            corners_lat=np.asarray(value["corners_lat"], dtype=np.float64),
            corners_lon=np.asarray(value["corners_lon"], dtype=np.float64),
            inside_region=np.asarray(value["inside_region"], dtype=bool),
            is_land=np.asarray(value["is_land"], dtype=bool),
            land_ratio=np.asarray(value["land_ratio"], dtype=np.float64),
            depth_m=np.asarray(value["depth_m"], dtype=np.float64),
            static_traversable=np.asarray(value["static_traversable"], dtype=bool),
        )
