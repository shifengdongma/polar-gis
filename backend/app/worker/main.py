import logging
import socket
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import (
    ImportJob,
    JobStatus,
    PlanningRun,
    PlanningRunStatus,
    S57ImportBatch,
    S57ImportBatchItem,
)
from app.navigation.tasks.processor import PlanningRunProcessor
from app.services.importer import ImportProcessor
from app.services.s57_batch import S57BatchProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("polar_gis.worker")
settings = get_settings()


def claim_job(session_factory=SessionLocal) -> ImportJob | None:
    with session_factory() as db:
        stale_before = datetime.now(UTC) - timedelta(minutes=10)
        stale_jobs = db.scalars(
            select(ImportJob).where(
                ImportJob.status == JobStatus.RUNNING.value,
                ImportJob.heartbeat_at < stale_before,
            )
        ).all()
        for stale in stale_jobs:
            stale.status = JobStatus.FAILED.value
            stale.stage = "failed"
            stale.error_code = "WORKER_HEARTBEAT_TIMEOUT"
            stale.error_message = "Worker心跳超时"
            stale.finished_at = datetime.now(UTC)
        job = db.scalar(
            select(ImportJob)
            .where(ImportJob.status == JobStatus.QUEUED.value)
            .order_by(ImportJob.queued_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            db.commit()
            return None
        job.status = JobStatus.RUNNING.value
        job.worker_id = socket.gethostname()
        job.attempt += 1
        job.started_at = datetime.now(UTC)
        job.heartbeat_at = datetime.now(UTC)
        db.commit()
        db.expunge(job)
        return job


def claim_batch(session_factory=SessionLocal) -> S57ImportBatch | None:
    with session_factory() as db:
        stale_before = datetime.now(UTC) - timedelta(minutes=30)
        stale_batches = db.scalars(
            select(S57ImportBatch).where(
                S57ImportBatch.status == JobStatus.RUNNING.value,
                S57ImportBatch.heartbeat_at < stale_before,
            )
        ).all()
        for stale in stale_batches:
            active_items = db.scalars(
                select(S57ImportBatchItem).where(
                    S57ImportBatchItem.batch_id == stale.id,
                    S57ImportBatchItem.status.in_(
                        [JobStatus.QUEUED.value, JobStatus.RUNNING.value]
                    ),
                )
            ).all()
            for item in active_items:
                item.status = JobStatus.FAILED.value
                item.stage = "worker_timeout"
                item.error_code = "WORKER_HEARTBEAT_TIMEOUT"
                item.error_message = "批量导入Worker心跳超时"
                item.finished_at = datetime.now(UTC)
            stale.status = JobStatus.FAILED.value
            stale.stage = "worker_timeout"
            stale.processed_cells = min(
                stale.total_cells,
                stale.processed_cells + len(active_items),
            )
            stale.failed_cells = max(stale.failed_cells + len(active_items), 1)
            if stale.total_cells:
                stale.progress = int(stale.processed_cells * 100 / stale.total_cells)
            stale.finished_at = datetime.now(UTC)
        batch = db.scalar(
            select(S57ImportBatch)
            .where(S57ImportBatch.status == JobStatus.QUEUED.value)
            .order_by(S57ImportBatch.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if batch is None:
            db.commit()
            return None
        batch.status = JobStatus.RUNNING.value
        batch.worker_id = socket.gethostname()
        batch.started_at = datetime.now(UTC)
        batch.heartbeat_at = datetime.now(UTC)
        db.commit()
        db.expunge(batch)
        return batch


def claim_planning_run(session_factory=SessionLocal) -> PlanningRun | None:
    with session_factory() as db:
        stale_before = datetime.now(UTC) - timedelta(minutes=10)
        stale_runs = db.scalars(
            select(PlanningRun).where(
                PlanningRun.status == PlanningRunStatus.RUNNING.value,
                PlanningRun.heartbeat_at < stale_before,
            )
        ).all()
        for stale in stale_runs:
            stale.status = PlanningRunStatus.FAILED.value
            stale.stage = "failed"
            stale.error_code = "WORKER_HEARTBEAT_TIMEOUT"
            stale.error_message = "Worker心跳超时"
            stale.finished_at = datetime.now(UTC)
        run = db.scalar(
            select(PlanningRun)
            .where(PlanningRun.status == PlanningRunStatus.QUEUED.value)
            .order_by(PlanningRun.queued_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if run is None:
            db.commit()
            return None
        run.status = PlanningRunStatus.RUNNING.value
        run.stage = "planning"
        run.progress = max(1, run.progress)
        run.worker_id = socket.gethostname()
        run.started_at = datetime.now(UTC)
        run.heartbeat_at = datetime.now(UTC)
        db.commit()
        db.expunge(run)
        return run


def run_once(session_factory=SessionLocal) -> bool:
    """Execute at most one import batch, import job, or planning run.

    Kept injectable for tests (SQLite TestSession) without changing the
    production worker loop.  Planning failures are contained inside the
    planner processor and never terminate the worker.
    """
    batch = claim_batch(session_factory)
    if batch is not None:
        with session_factory() as db:
            attached_batch = db.get(S57ImportBatch, batch.id)
            if attached_batch:
                S57BatchProcessor(settings).process(db, attached_batch)
        return True
    job = claim_job(session_factory)
    if job is not None:
        with session_factory() as db:
            attached_job = db.get(ImportJob, job.id)
            if attached_job:
                ImportProcessor(settings).process(db, attached_job)
        return True
    planning = claim_planning_run(session_factory)
    if planning is not None:
        try:
            PlanningRunProcessor(settings).process(planning.id, session_factory)
        except Exception:  # noqa: BLE001 - the only worker must keep running
            logger.exception("Planning run %s escaped the processor", planning.id)
        return True
    return False


def run() -> None:
    logger.info("Polar GIS worker started")
    while True:
        if not run_once():
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    run()
