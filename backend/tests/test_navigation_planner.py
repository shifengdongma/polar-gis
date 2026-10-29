"""D* Lite, NSGA-III and edge-transit consistency tests on a small grid."""

from math import isclose

import numpy as np

from app.navigation.planner.dnsga3 import evaluate_path, run_nsga3
from app.navigation.planner.dstar import DStarLite
from app.navigation.planner.energy_model import calculate_edge_transit
from app.navigation.planner.grid import PlanningGrid
from app.navigation.vessel.models import VesselProfile


def vessel(power_mw: float = 15.0, max_speed_kn: float = 18.0) -> VesselProfile:
    return VesselProfile(
        id="test",
        name="test",
        vessel_type="test",
        length_m=100,
        beam_m=20,
        design_draft_m=7.85,
        total_propulsion_power_mw=power_mw,
        service_speed_min_kn=12,
        service_speed_max_kn=15,
        maximum_speed_kn=max_speed_kn,
        continuous_ice_thickness_m=1.5,
        safety_draft_m=7.85,
        safety_power_mw=power_mw,
        safety_speed_limit_kn=max_speed_kn,
        ukc_m=2.0,
    )


def small_grid(vessel_profile: VesselProfile, *, current_u: float = 0.0, wind_u: float = 0.0) -> PlanningGrid:
    size = 10
    latitude = np.repeat(np.linspace(70.0, 72.0, size)[:, None], size, axis=1)
    longitude = np.repeat(np.linspace(120.0, 123.0, size)[None, :], size, axis=0)
    risk = np.full((size, size), 0.1, dtype=float)
    obstacle = np.zeros((size, size), dtype=bool)
    obstacle[0, :] = obstacle[-1, :] = True
    obstacle[:, 0] = obstacle[:, -1] = True
    metadata = {}
    for row in range(size):
        for column in range(size):
            metadata[(column, row)] = {
                "environment": {
                    "ice_concentration": 0.2,
                    "ice_thickness_m": 0.4,
                    "wind_u_ms": wind_u,
                    "wind_v_ms": 0.0,
                    "wave_height_m": 1.0,
                    "wave_direction_deg": 240.0,
                    "current_u_ms": current_u,
                    "current_v_ms": 0.0,
                }
            }
    return PlanningGrid(
        latitudes=latitude,
        longitudes=longitude,
        risk=risk,
        obstacle=obstacle,
        factors={name: np.full((size, size), 0.1) for name in ("ice", "depth", "fog", "wind", "wave")},
        cell_metadata=metadata,
        start=(1, 1),
        goal=(8, 8),
        vessel=vessel_profile,
        cell_size_m=25_000.0,
    )


def test_edge_transit_returns_same_result_for_all_objectives() -> None:
    grid = small_grid(vessel())
    result = grid.edge_result((1, 1), (2, 2))
    assert result.feasible is True
    assert result.speed_through_water_kn > 0
    assert result.energy_mwh > 0
    assert isclose(result.energy_mwh, result.total_power_mw * result.travel_time_h)
    assert grid.edge((1, 1), (2, 2)) == (result.risk, result.energy_mwh, result.travel_time_h)


def test_current_along_track_increases_ground_speed() -> None:
    base = small_grid(vessel(), current_u=0.0)
    assisted = small_grid(vessel(), current_u=1.0)
    base_result = base.edge_result((1, 1), (2, 1))
    assisted_result = assisted.edge_result((1, 1), (2, 1))
    assert assisted_result.speed_over_ground_kn > base_result.speed_over_ground_kn


def test_headwind_reduces_speed_at_the_power_limit() -> None:
    headwind = small_grid(vessel(), wind_u=-12.0)
    tailwind = small_grid(vessel(), wind_u=12.0)
    headwind_edge = headwind.edge_result((1, 1), (2, 1))
    tailwind_edge = tailwind.edge_result((1, 1), (2, 1))
    assert headwind_edge.power_limited is True
    assert tailwind_edge.power_limited is True
    assert headwind_edge.speed_through_water_kn < tailwind_edge.speed_through_water_kn


def test_two_vessels_produce_different_speed_and_energy() -> None:
    strong = small_grid(vessel(power_mw=15.0, max_speed_kn=18.0))
    weak = small_grid(vessel(power_mw=5.0, max_speed_kn=14.0))
    strong_edge = strong.edge_result((1, 1), (2, 1))
    weak_edge = weak.edge_result((1, 1), (2, 1))
    assert strong_edge.speed_through_water_kn > weak_edge.speed_through_water_kn
    assert strong_edge.energy_mwh != weak_edge.energy_mwh


def test_dstar_finds_a_path_and_evaluate_path_is_consistent() -> None:
    grid = small_grid(vessel())
    path = DStarLite(grid, "risk").plan()
    assert path
    assert path[0] == grid.start
    assert path[-1] == grid.goal
    objectives = evaluate_path(grid, path)
    assert np.all(np.isfinite(objectives))
    assert objectives[0] >= 0
    assert objectives[1] > 0
    assert objectives[2] > 0


def test_nsga3_returns_pareto_candidates_with_three_objectives() -> None:
    grid = small_grid(vessel())
    front = run_nsga3(grid, population_size=8, generations=2, seed=7)
    assert front
    assert all(item.objectives.shape == (3,) for item in front)
    assert all(np.all(np.isfinite(item.objectives)) for item in front)
    # Unique paths and non-dominated objective vectors.
    assert len({tuple(item.path) for item in front}) == len(front)
    for index, item in enumerate(front):
        for other_index, other in enumerate(front):
            if index == other_index:
                continue
            assert not (np.all(other.objectives <= item.objectives) and np.any(other.objectives < item.objectives))
