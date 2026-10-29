"""Planner service and adopted-route evaluation tests on a small grid."""

from datetime import UTC, datetime

from app.navigation.contracts import DataQuality, TimeMatchInfo
from app.navigation.environment.models import (
    EnvironmentSnapshot,
    FieldObservation,
    FieldSnapshotInfo,
)
from app.navigation.planner.service import PlanningRequest, PlannerService
from app.navigation.vessel.service import VesselService
from test_navigation_grid import DEPARTURE, FakeService, small_static_grid


class SnapshotFakeService(FakeService):
    def snapshot(self, requested_time, policy):
        return EnvironmentSnapshot(
            requested_time=requested_time,
            data_policy=policy,
            quality_summary=DataQuality.REAL,
            fields={
                field: FieldSnapshotInfo(
                    field=field,
                    available=True,
                    source="fake",
                    quality=DataQuality.REAL,
                    matched_time=requested_time,
                )
                for field in ("bathymetry", "ice", "wind", "current", "wave")
            },
        )


def test_plan_and_evaluate_adopted_route() -> None:
    service = PlannerService(
        SnapshotFakeService(),  # type: ignore[arg-type]
        VesselService(),
        small_static_grid(),
    )
    outcome = service.plan(
        PlanningRequest(
            start_longitude=120.0,
            start_latitude=75.0,
            goal_longitude=122.0,
            goal_latitude=77.0,
            departure=DEPARTURE,
            vessel_id="xuelong2",
            data_policy="allow_synthetic_research",
            population_size=8,
            generations=2,
            seed=11,
        )
    )
    assert outcome.routes
    recommended = next(route for route in outcome.routes if route["recommended"])
    assert recommended["riskScore"] >= 0
    assert recommended["energyMWh"] > 0
    assert recommended["timeHours"] > 0
    assert recommended["distanceKm"] > 0
    assert recommended["coordinates"][0] != recommended["coordinates"][-1]
    assert outcome.risk_grid["cells"]

    coordinates = [tuple(point) for point in recommended["coordinates"]]
    evaluation = service.evaluate_route(outcome.risk_grid, coordinates, VesselProfileForTest())
    assert evaluation["traversable"] is True, evaluation
    assert evaluation["energyMWh"] > 0
    assert evaluation["timeHours"] > 0
    assert evaluation["distanceKm"] > 0


def VesselProfileForTest():
    return VesselService().get("xuelong2")


def test_risk_only_returns_grid_without_routes() -> None:
    service = PlannerService(
        SnapshotFakeService(),  # type: ignore[arg-type]
        VesselService(),
        small_static_grid(),
    )
    outcome = service.risk_only(
        PlanningRequest(
            start_longitude=120.0,
            start_latitude=75.0,
            goal_longitude=120.0,
            goal_latitude=75.0,
            departure=DEPARTURE,
            vessel_id="xuelong2",
            data_policy="allow_synthetic_research",
            bbox=(119.0, 74.0, 121.0, 76.0),
        )
    )
    assert outcome.routes == []
    assert outcome.risk_grid["cells"]
    assert all(
        cell["traversable"] is True
        for cell in outcome.risk_grid["cells"]
        if not cell["isLand"]
    )


def test_evaluate_route_rejects_land_crossing() -> None:
    service = PlannerService(
        SnapshotFakeService(),  # type: ignore[arg-type]
        VesselService(),
        small_static_grid(),
    )
    outcome = service.plan(
        PlanningRequest(
            start_longitude=120.0,
            start_latitude=75.0,
            goal_longitude=122.0,
            goal_latitude=77.0,
            departure=DEPARTURE,
            vessel_id="xuelong2",
            data_policy="allow_synthetic_research",
            population_size=8,
            generations=2,
            seed=3,
        )
    )
    evaluation = service.evaluate_route(
        outcome.risk_grid,
        [(120.0, 75.0), (122.0, 77.0)],
        VesselProfileForTest(),
    )
    assert evaluation["traversable"] is False
    assert evaluation["reason"]
