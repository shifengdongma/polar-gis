import logging
import socket
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import ImportJob, JobStatus, S57ImportBatch, S57ImportBatchItem
from app.services.importer import ImportProcessor
from app.services.s57_batch import S57BatchProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("polar_gis.worker")
settings = get_settings()


def claim_job() -> ImportJob | None:
    with SessionLocal() as db:
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


def claim_batch() -> S57ImportBatch | None:
    with SessionLocal() as db:
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


def run() -> None:
    processor = ImportProcessor(settings)
    batch_processor = S57BatchProcessor(settings)
    logger.info("Polar GIS worker started")
    while True:
        batch = claim_batch()
        if batch is not None:
            with SessionLocal() as db:
                attached_batch = db.get(S57ImportBatch, batch.id)
                if attached_batch:
                    batch_processor.process(db, attached_batch)
            continue
        job = claim_job()
        if job is None:
            time.sleep(settings.worker_poll_seconds)
            continue
        with SessionLocal() as db:
            attached_job = db.get(ImportJob, job.id)
            if attached_job:
                processor.process(db, attached_job)


if __name__ == "__main__":
    run()
