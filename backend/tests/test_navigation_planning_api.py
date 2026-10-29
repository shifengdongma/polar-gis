"""Planning task API tests (queue lifecycle, access, risk-only creation)."""

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import PlanningRoute, PlanningRun, Project, ProjectStatus, User


@pytest.fixture
def published_project(db_session: Session) -> Project:
    admin = db_session.scalar(select(User).where(User.username == "admin"))
    assert admin is not None
    project = Project(
        code=f"nav-{uuid4().hex[:8]}",
        name="Navigation test project",
        description="",
        status=ProjectStatus.PUBLISHED.value,
        default_crs="EPSG:3857",
        created_by=admin.id,
        updated_by=admin.id,
        published_at=datetime.now(UTC),
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    return project


def create_payload(project: Project) -> dict:
    return {
        "projectId": str(project.id),
        "start": {"longitude": 120.0, "latitude": 75.0},
        "goal": {"longitude": 122.0, "latitude": 77.0},
        "departureTime": "2025-02-15T12:00:00Z",
        "vesselId": "xuelong2",
        "dataPolicy": "allow_synthetic_research",
        "algorithm": "dnsga3",
        "objectives": ["risk", "energy", "time"],
        "populationSize": 8,
        "generations": 2,
        "seed": 7,
    }


def test_create_list_get_and_cancel_plan(
    client: TestClient,
    user_headers: dict[str, str],
    published_project: Project,
) -> None:
    response = client.post(
        "/api/v1/navigation/plans",
        headers=user_headers,
        json=create_payload(published_project),
    )
    assert response.status_code == 202, response.text
    run = response.json()
    plan_id = run["planId"]
    assert run["status"] == "queued"
    assert run["riskModelVersion"] == "legacy_v1"

    listed = client.get(
        "/api/v1/navigation/plans",
        headers=user_headers,
        params={"project_id": str(published_project.id)},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["planId"] == plan_id

    detail = client.get(f"/api/v1/navigation/plans/{plan_id}", headers=user_headers)
    assert detail.status_code == 200
    assert detail.json()["vesselId"] == "xuelong2"

    cancelled = client.post(
        f"/api/v1/navigation/plans/{plan_id}/cancel", headers=user_headers
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    again = client.post(
        f"/api/v1/navigation/plans/{plan_id}/cancel", headers=user_headers
    )
    assert again.status_code == 409


def test_create_plan_rejects_invalid_objectives_and_outside_grid(
    client: TestClient,
    user_headers: dict[str, str],
    published_project: Project,
) -> None:
    payload = create_payload(published_project)
    payload["objectives"] = ["risk", "energy"]
    response = client.post("/api/v1/navigation/plans", headers=user_headers, json=payload)
    assert response.status_code == 422

    payload = create_payload(published_project)
    payload["start"] = {"longitude": 0.0, "latitude": 0.0}
    response = client.post("/api/v1/navigation/plans", headers=user_headers, json=payload)
    assert response.status_code == 422


def test_risk_only_evaluation_creates_queued_task(
    client: TestClient,
    user_headers: dict[str, str],
    published_project: Project,
) -> None:
    response = client.post(
        "/api/v1/navigation/risk/evaluate",
        headers=user_headers,
        json={
            "projectId": str(published_project.id),
            "bbox": [120.0, 75.0, 122.0, 77.0],
            "departureTime": "2025-02-15T12:00:00Z",
            "vesselId": "xuelong2",
            "dataPolicy": "allow_synthetic_research",
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["mode"] == "risk_only"
    assert response.json()["status"] == "queued"


def test_plans_require_auth(client: TestClient) -> None:
    assert client.get("/api/v1/navigation/plans").status_code == 401


def test_risk_grid_requires_completed_result(
    client: TestClient,
    user_headers: dict[str, str],
    published_project: Project,
) -> None:
    response = client.post(
        "/api/v1/navigation/plans",
        headers=user_headers,
        json=create_payload(published_project),
    )
    plan_id = response.json()["planId"]
    risk_grid = client.get(
        f"/api/v1/navigation/plans/{plan_id}/risk-grid", headers=user_headers
    )
    assert risk_grid.status_code == 409
    assert risk_grid.json()["code"] == "PLANNER_RESULT_NOT_READY"


def test_risk_grid_features_and_routes_are_scoped_to_plan(
    client: TestClient,
    user_headers: dict[str, str],
    published_project: Project,
    db_session: Session,
) -> None:
    response = client.post(
        "/api/v1/navigation/plans",
        headers=user_headers,
        json=create_payload(published_project),
    )
    plan_id = response.json()["planId"]
    run = db_session.get(PlanningRun, UUID(plan_id))
    assert run is not None
    run.status = "completed"
    run.stage = "completed"
    run.risk_grid_path = f"{plan_id}.json.gz"
    run.algorithm_version = "dnsge3-test"
    db_session.add(
        PlanningRoute(
            run_id=run.id,
            route_index=0,
            route_id="route-0",
            is_recommended=True,
            label="最低风险",
            coordinates_json=[[120.0, 75.0], [121.0, 76.0]],
            risk_score=0.2,
            energy_mwh=12.5,
            time_hours=4.5,
            distance_km=140.0,
            quality="synthetic",
            algorithm_version="dnsga3-test",
        )
    )
    db_session.commit()

    result_root = Path(get_settings().planner_result_root)
    result_root.mkdir(parents=True, exist_ok=True)
    with gzip.open(result_root / f"{plan_id}.json.gz", "wt", encoding="utf-8") as handle:
        json.dump(
            {
                "width": 1,
                "height": 1,
                "cells": [
                    {
                        "cellId": "r0c0",
                        "center": {"latitude": 75.0, "longitude": 120.0},
                        "geometry": [
                            [119.5, 74.5],
                            [120.5, 74.5],
                            [120.5, 75.5],
                            [119.5, 75.5],
                        ],
                        "risk": {"combined": 0.2, "ice": 0.3, "depth": 0.1, "fog": None, "wind": 0.1, "wave": 0.0},
                        "quality": {"combined": "synthetic"},
                        "traversable": True,
                        "riskModelVersion": "legacy_v1",
                    }
                ],
            },
            handle,
        )

    grid = client.get(
        f"/api/v1/navigation/plans/{plan_id}/risk-grid",
        headers=user_headers,
        params={"field": "combined"},
    )
    assert grid.status_code == 200, grid.text
    assert grid.json()["returnedCells"] == 1
    assert grid.json()["features"][0]["properties"]["cellId"] == "r0c0"

    cell = client.get(
        f"/api/v1/navigation/plans/{plan_id}/risk-grid/r0c0", headers=user_headers
    )
    assert cell.status_code == 200
    assert cell.json()["risk"]["combined"] == pytest.approx(0.2)

    routes = client.get(
        f"/api/v1/navigation/plans/{plan_id}/routes", headers=user_headers
    )
    assert routes.status_code == 200, routes.text
    assert routes.json()[0]["routeId"] == "route-0"
    assert routes.json()[0]["recommended"] is True
