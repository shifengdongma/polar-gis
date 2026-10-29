"""End-to-end synthetic-research test through the real Polar-GIS API + planner.

This is NOT a real-environment validation.  It uses navigation_manifest.json
fixtures marked ``quality=synthetic`` and only ``allow_synthetic_research``.
The worker processor is invoked in-process so the script needs no external
container; the API surface, database models, planner, risk grid and evaluation
are the production code paths.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FIXTURES = ROOT / "sample-data" / "navigation"
WORK = BACKEND / ".e2e-navigation"
DB_PATH = WORK / "e2e.db"
STORAGE = WORK / "storage"
RESULTS = WORK / "planner-results"

os.environ.update(
    {
        "DATABASE_URL": f"sqlite+pysqlite:///{DB_PATH.as_posix()}",
        "APP_SECRET_KEY": "e2e-navigation-secret-key-with-sufficient-length",
        "APP_ENV": "test",
        "AUTO_CREATE_SCHEMA": "true",
        "COOKIE_SECURE": "false",
        "INITIAL_ADMIN_USERNAME": "admin",
        "INITIAL_ADMIN_PASSWORD": "AdminPass123!",
        "GWC_3413_BACKFILL": "0",
        "STORAGE_ROOT": str(STORAGE),
        "TEMP_ROOT": str(STORAGE / "temp"),
        "NAVIGATION_ENABLED": "true",
        "NAVIGATION_DATA_ROOT": str(FIXTURES),
        "NAVIGATION_ICE_DATA_ROOT": str(FIXTURES / "ice"),
        "NAVIGATION_ICE_BACKEND": "nextsim",
        "NAVIGATION_MANIFEST_PATH": str(FIXTURES / "navigation_manifest.json"),
        "NAVIGATION_DEFAULT_DATA_POLICY": "allow_synthetic_research",
        "PLANNER_RESULT_ROOT": str(RESULTS),
        "PLANNER_MAX_GENERATIONS": "100",
        "PLANNER_TIMEOUT_SECONDS": "300",
    }
)

sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Project, ProjectStatus, User  # noqa: E402
from app.navigation.tasks.processor import PlanningRunProcessor  # noqa: E402

settings = get_settings()


def reset_workdir() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    STORAGE.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)


def seed_project() -> UUID:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        if admin is None:
            from app.core.security import hash_password

            admin = User(
                username="admin",
                display_name="E2E Admin",
                password_hash=hash_password("AdminPass123!"),
                role="system_admin",
                is_active=True,
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)
        project = Project(
            code="e2e-navigation",
            name="E2E Navigation",
            description="Synthetic research validation only",
            status=ProjectStatus.PUBLISHED.value,
            default_crs="EPSG:3857",
            created_by=admin.id,
            updated_by=admin.id,
            published_at=datetime.now(UTC),
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return project.id


def login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPass123!"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def plan_payload(project_id: UUID, policy: str) -> dict:
    return {
        "projectId": str(project_id),
        "start": {"longitude": 120.0, "latitude": 75.0},
        "goal": {"longitude": 122.0, "latitude": 77.0},
        "departureTime": "2025-02-15T12:00:00Z",
        "vesselId": "xuelong2",
        "dataPolicy": policy,
        "algorithm": "dnsga3",
        "objectives": ["risk", "energy", "time"],
        "populationSize": 8,
        "generations": 2,
        "seed": 7,
    }


def create_plan(client: TestClient, headers: dict[str, str], project_id: UUID, policy: str) -> str:
    response = client.post(
        "/api/v1/navigation/plans",
        headers=headers,
        json=plan_payload(project_id, policy),
    )
    assert response.status_code == 202, response.text
    return response.json()["planId"]


def run_worker(plan_id: str) -> None:
    import socket

    from app.models import PlanningRun, PlanningRunStatus

    with SessionLocal() as db:
        run = db.get(PlanningRun, UUID(plan_id))
        assert run is not None
        run.status = PlanningRunStatus.RUNNING.value
        run.stage = "planning"
        run.worker_id = socket.gethostname()
        run.started_at = datetime.now(UTC)
        run.heartbeat_at = datetime.now(UTC)
        db.commit()
    PlanningRunProcessor(settings).process(UUID(plan_id), SessionLocal)


def get_plan(client: TestClient, headers: dict[str, str], plan_id: str) -> dict:
    response = client.get(f"/api/v1/navigation/plans/{plan_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def main() -> int:
    reset_workdir()
    project_id = seed_project()
    started = time.perf_counter()
    with TestClient(app) as client:
        headers = login(client)
        sources = client.get(
            "/api/v1/navigation/environment/sources", headers=headers
        )
        assert sources.status_code == 200, sources.text
        assert all(item["quality"] == "synthetic" for item in sources.json()), sources.text

        query = client.post(
            "/api/v1/navigation/environment/query",
            headers=headers,
            json={
                "longitude": 120.0,
                "latitude": 75.0,
                "time": "2025-02-15T12:00:00Z",
                "fields": ["bathymetry", "ice", "wind", "current", "wave"],
                "dataPolicy": "allow_synthetic_research",
            },
        )
        assert query.status_code == 200, query.text
        wind = query.json()["fields"]["wind"]
        assert wind["available"] is True, query.text
        print(f"environment query OK: wind={wind['values']['speedMs']} m/s quality={wind['quality']}")

        vessels = client.get("/api/v1/navigation/vessels", headers=headers)
        assert vessels.status_code == 200 and vessels.json()[0]["id"] == "xuelong2"

        plan_id = create_plan(client, headers, project_id, "allow_synthetic_research")
        worker_started = time.perf_counter()
        run_worker(plan_id)
        plan = get_plan(client, headers, plan_id)
        elapsed = time.perf_counter() - worker_started
        assert plan["status"] == "completed", plan
        routes = client.get(
            f"/api/v1/navigation/plans/{plan_id}/routes", headers=headers
        )
        assert routes.status_code == 200 and routes.json(), routes.text
        recommended = next(route for route in routes.json() if route["recommended"])
        assert recommended["coordinates"]
        print(
            f"plan OK: {len(routes.json())} routes, recommended risk={recommended['riskScore']:.3f}, "
            f"energy={recommended['energyMWh']:.2f} MWh, time={recommended['timeHours']:.2f} h, "
            f"worker={elapsed:.1f}s"
        )

        risk = client.get(
            f"/api/v1/navigation/plans/{plan_id}/risk-grid",
            headers=headers,
            params={"field": "combined", "stride": 20},
        )
        assert risk.status_code == 200, risk.text
        assert risk.json()["returnedCells"] > 0
        print(f"risk grid OK: {risk.json()['returnedCells']} features")

        evaluated = client.post(
            f"/api/v1/navigation/plans/{plan_id}/evaluate-route",
            headers=headers,
            json={"coordinates": recommended["coordinates"]},
        )
        assert evaluated.status_code == 200, evaluated.text
        assert evaluated.json()["traversable"] is True, evaluated.text
        evaluated_json = evaluated.json()
        assert abs(evaluated_json["energyMWh"] - recommended["energyMWh"]) < 1e-6
        assert abs(evaluated_json["timeHours"] - recommended["timeHours"]) < 1e-6
        assert abs(evaluated_json["riskScore"] - recommended["riskScore"]) < 1e-6
        print(
            f"adopted-route evaluation OK: risk={evaluated_json['riskScore']:.3f}, "
            f"energy={evaluated_json['energyMWh']:.2f} MWh, time={evaluated_json['timeHours']:.2f} h "
            "(identical to candidate)"
        )

        real_only_response = client.post(
            "/api/v1/navigation/plans",
            headers=headers,
            json=plan_payload(project_id, "real_only"),
        )
        assert real_only_response.status_code == 422, real_only_response.text
        assert real_only_response.json()["code"] == "ENVIRONMENT_DATA_MISSING"
        print("real_only negative OK: synthetic fixtures rejected before queue")

        area = client.post(
            "/api/v1/navigation/risk/evaluate",
            headers=headers,
            json={
                "projectId": str(project_id),
                "bbox": [120.0, 75.0, 122.0, 77.0],
                "departureTime": "2025-02-15T12:00:00Z",
                "vesselId": "xuelong2",
                "dataPolicy": "allow_synthetic_research",
            },
        )
        assert area.status_code == 202, area.text
        run_worker(area.json()["planId"])
        area_plan = get_plan(client, headers, area.json()["planId"])
        assert area_plan["status"] == "completed", area_plan
        print("risk-only area evaluation OK")

    print(f"E2E synthetic-research chain completed in {time.perf_counter() - started:.1f}s")
    print("NOTE: this is synthetic research validation, not real-environment planning.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
