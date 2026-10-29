"""Static planning grid and environment adapter tests."""

from datetime import UTC, datetime

import numpy as np
import pytest

from app.navigation.contracts import DataQuality, TimeMatchInfo
from app.navigation.environment.models import FieldObservation
from app.navigation.planner.environment_adapter import (
    EnvironmentDataMissing,
    build_planning_grid,
)
from app.navigation.planner.static_grid import (
    StaticPlanningGrid,
    load_static_grid,
)
from app.navigation.vessel.models import VesselProfile

DEPARTURE = datetime(2025, 2, 15, 12, tzinfo=UTC)


def vessel() -> VesselProfile:
    return VesselProfile(
        id="test",
        name="test",
        vessel_type="test",
        length_m=100,
        beam_m=20,
        design_draft_m=7.85,
        total_propulsion_power_mw=15,
        service_speed_min_kn=12,
        service_speed_max_kn=15,
        maximum_speed_kn=18,
        continuous_ice_thickness_m=1.5,
        safety_draft_m=7.85,
        safety_power_mw=15,
        safety_speed_limit_kn=18,
        ukc_m=2.0,
    )


class FakeService:
    def __init__(self, missing: set[str] | None = None) -> None:
        self.missing = missing or set()

    def sample_many(self, field, points, requested_time, policy):
        result = []
        for longitude, latitude in points:
            if field in self.missing:
                result.append(_observation(field, available=False, reason="test_missing"))
            else:
                result.append(_observation(field))
        return result


def _observation(field: str, *, available: bool = True, reason: str | None = None) -> FieldObservation:
    values = {
        "bathymetry": {"depthM": 100.0, "isLand": False},
        "ice": {"concentration": 0.2, "thicknessM": 0.5},
        "wind": {"speedMs": 10.0, "directionFromDeg": 270.0, "uMs": 10.0, "vMs": 0.0},
        "current": {"uMs": 0.2, "vMs": 0.0, "speedMs": 0.2, "directionToDeg": 90.0},
        "wave": {"heightM": 1.0, "periodS": 7.0, "directionFromDeg": 240.0},
    }[field]
    return FieldObservation(
        field=field,
        available=available,
        values=values if available else {},
        units={},
        component_quality={key: DataQuality.REAL for key in values} if available else {},
        quality=DataQuality.REAL if available else DataQuality.MISSING,
        source="fake",
        time=TimeMatchInfo(requested_time=DEPARTURE, matched_time=DEPARTURE, quality="exact"),
        reason=reason,
    )


def small_static_grid() -> StaticPlanningGrid:
    size = 20
    lat = np.repeat(np.linspace(74.0, 78.0, size)[:, None], size, axis=1)
    lon = np.repeat(np.linspace(119.0, 123.0, size)[None, :], size, axis=0)
    corners_lat = np.stack([lat - 0.05, lat - 0.05, lat + 0.05, lat + 0.05], axis=2)
    corners_lon = np.stack([lon - 0.05, lon + 0.05, lon + 0.05, lon - 0.05], axis=2)
    land = np.zeros((size, size), dtype=bool)
    # A partial barrier leaves a navigable channel at the eastern edge.
    land[8:12, : size - 4] = True
    traversable = ~land
    return StaticPlanningGrid(
        metadata={
            "version": 3,
            "region": {
                "south": 73.0,
                "north": 79.0,
                "west": 118.0,
                "east": 124.0,
                "planning_west": 118.0,
                "planning_east": 124.0,
            },
            "cell_size_m": 25_000,
            "crs": "EPSG:3413",
        },
        center_lat=lat,
        center_lon=lon,
        corners_lat=corners_lat,
        corners_lon=corners_lon,
        inside_region=np.ones((size, size), dtype=bool),
        is_land=land,
        land_ratio=land.astype(float),
        depth_m=np.where(land, 0.0, 100.0),
        static_traversable=traversable,
    )


def test_resource_grid_has_expected_shape_and_counts() -> None:
    grid = load_static_grid()
    assert grid.shape == (110, 240)
    assert int(grid.inside_region.sum()) == 15_731
    assert int(grid.static_traversable.sum()) == 8_738
    cell = grid.nearest_cell(75.0, 120.0)
    assert cell is not None
    lat, lon = grid.cell_center(*cell)
    assert 50 < lat < 90
    assert -180 <= lon <= 180


def test_build_grid_synthetic_policy_marks_quality_and_obstacles() -> None:
    result = build_planning_grid(
        small_static_grid(),
        FakeService(),
        DEPARTURE,
        vessel(),
        "allow_synthetic_research",
        start=(120.0, 75.0),
        goal=(122.0, 77.0),
    )
    assert len(result.cells) == 400
    assert result.grid.start != result.grid.goal
    assert result.grid.obstacle.sum() >= 60  # partial land strip
    start_cell = result.grid.cell_metadata[result.grid.start]
    assert start_cell["riskModelVersion"] == "legacy_v1"
    assert start_cell["environment"]["ice_concentration"] == pytest.approx(0.2)
    assert any(cell["quality"]["ice"] == "real" for cell in result.cells if not cell["isLand"])


def test_build_grid_real_only_keeps_unknown_fog_not_zero() -> None:
    result = build_planning_grid(
        small_static_grid(),
        FakeService(),
        DEPARTURE,
        vessel(),
        "real_only",
        start=(120.0, 75.0),
        goal=(122.0, 77.0),
    )
    cell = result.grid.cell_metadata[result.grid.start]
    assert cell["riskModelVersion"] == "real_v1"
    assert cell["risk"]["fog"] is None
    assert cell["quality"]["fog"] == "missing"


def test_build_grid_real_only_fails_when_whole_field_missing() -> None:
    with pytest.raises(EnvironmentDataMissing) as error:
        build_planning_grid(
            small_static_grid(),
            FakeService(missing={"wind"}),
            DEPARTURE,
            vessel(),
            "real_only",
            start=(120.0, 75.0),
            goal=(122.0, 77.0),
        )
    assert "wind" in error.value.fields
