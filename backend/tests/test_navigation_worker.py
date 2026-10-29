"""Worker claim/process integration and failure containment tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api import navigation_environment
from app.core.config import get_settings
from app.models import PlanningRun, PlanningRunStatus, Project, ProjectStatus, User
from app.navigation.tasks import processor as processor_module
from app.navigation.tasks.service import PlanningTaskService
from app.worker import main as worker_main


def make_project(db: Session) -> Project:
    admin = db.scalar(select(User).where(User.username == "admin"))
    assert admin is not None
    project = Project(
        code=f"worker-{uuid4().hex[:8]}",
        name="Worker test",
        status=ProjectStatus.PUBLISHED.value,
        created_by=admin.id,
        updated_by=admin.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def make_run(db: Session, project: Project) -> PlanningRun:
    admin = db.scalar(select(User).where(User.username == "admin"))
    assert admin is not None
    service = PlanningTaskService(get_settings())
    return service.create_run(
        db,
        project_id=project.id,
        requested_by=admin.id,
        vessel_id="xuelong2",
        mode="plan",
        data_policy="allow_synthetic_research",
        request_payload={
            "start": {"longitude": 120.0, "latitude": 75.0},
            "goal": {"longitude": 122.0, "latitude": 77.0},
            "departureTime": "2025-02-15T12:00:00Z",
            "vesselId": "xuelong2",
            "dataPolicy": "allow_synthetic_research",
            "populationSize": 8,
            "generations": 2,
            "seed": 7,
        },
        departure=datetime.now(UTC),
    )


def test_run_once_claims_and_completes_with_injected_processor(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_project(db_session)
    run = make_run(db_session, project)
    session_factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)

    class FakeProcessor:
        def __init__(self, settings) -> None:
            self.settings = settings

        def process(self, run_id, factory) -> None:
            with factory() as db:
                current = db.get(PlanningRun, run_id)
                assert current is not None
                current.status = PlanningRunStatus.COMPLETED.value
                current.stage = "completed"
                current.progress = 100
                current.finished_at = datetime.now(UTC)
                db.commit()

    monkeypatch.setattr(worker_main, "PlanningRunProcessor", FakeProcessor)
    assert worker_main.run_once(session_factory) is True
    with session_factory() as db:
        current = db.get(PlanningRun, run.id)
        assert current.status == PlanningRunStatus.COMPLETED.value


def test_planner_exception_marks_failed_without_killing_worker(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_project(db_session)
    run = make_run(db_session, project)
    session_factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)

    class FailingPlanner:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def plan(self, *args, **kwargs):
            raise RuntimeError("synthetic planner failure")

        def risk_only(self, *args, **kwargs):
            raise RuntimeError("synthetic planner failure")

    monkeypatch.setattr(processor_module, "PlannerService", FailingPlanner)
    # The real processor constructs EnvironmentService/VesselService; the
    # planner itself fails before touching environment data.
    assert worker_main.run_once(session_factory) is True
    with session_factory() as db:
        current = db.get(PlanningRun, run.id)
        assert current.status == PlanningRunStatus.FAILED.value
        assert current.error_code == "PLANNER_FAILED"


def test_stale_running_plan_is_failed_and_released(db_session: Session) -> None:
    project = make_project(db_session)
    run = make_run(db_session, project)
    run.status = PlanningRunStatus.RUNNING.value
    run.worker_id = "dead-worker"
    run.heartbeat_at = datetime.now(UTC) - timedelta(minutes=30)
    db_session.commit()
    session_factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    assert worker_main.claim_planning_run(session_factory) is None
    with session_factory() as db:
        current = db.get(PlanningRun, run.id)
        assert current.status == PlanningRunStatus.FAILED.value
        assert current.error_code == "WORKER_HEARTBEAT_TIMEOUT"
