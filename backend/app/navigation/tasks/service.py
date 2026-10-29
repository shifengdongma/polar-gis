"""Planning run lifecycle and cleanup."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import PlanningRoute, PlanningRun, PlanningRunStatus

from .errors import (
    PlanningLimitExceeded,
    PlanningNotCancellable,
    PlanningNotEditable,
    PlanningNotFound,
)


class PlanningTaskService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.result_root = Path(settings.planner_result_root)

    def create_run(
        self,
        db: Session,
        *,
        project_id: UUID,
        requested_by: UUID,
        vessel_id: str,
        mode: str,
        data_policy: str,
        request_payload: dict[str, object],
        departure: datetime,
        title: str | None = None,
    ) -> PlanningRun:
        active = db.scalar(
            select(func.count())
            .select_from(PlanningRun)
            .where(
                PlanningRun.requested_by == requested_by,
                PlanningRun.status.in_(
                    [PlanningRunStatus.QUEUED.value, PlanningRunStatus.RUNNING.value]
                ),
            )
        )
        if active is not None and active >= self.settings.planner_max_queued_runs:
            raise PlanningLimitExceeded(
                "Too many queued/running planning tasks; wait for one to finish."
            )
        run = PlanningRun(
            project_id=project_id,
            requested_by=requested_by,
            title=(title or "智能规划").strip()[:120],
            vessel_id=vessel_id,
            mode=mode,
            status=PlanningRunStatus.QUEUED.value,
            stage="queued",
            progress=0,
            request_json=request_payload,
            environment_snapshot_json={},
            algorithm_version="",
            data_policy=data_policy,
            risk_model_version="real_v1" if data_policy == "real_only" else "legacy_v1",
            result_summary_json={},
            cancel_requested=False,
            queued_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        self._cleanup_old_runs(db)
        return run

    def get_run(self, db: Session, plan_id: UUID) -> PlanningRun:
        run = db.get(PlanningRun, plan_id)
        if run is None:
            raise PlanningNotFound("Planning run not found.")
        return run

    def list_runs(
        self,
        db: Session,
        *,
        project_id: UUID,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[PlanningRun], int]:
        query = select(PlanningRun).where(PlanningRun.project_id == project_id)
        count_query = select(func.count()).select_from(PlanningRun).where(
            PlanningRun.project_id == project_id
        )
        if status:
            query = query.where(PlanningRun.status == status)
            count_query = count_query.where(PlanningRun.status == status)
        total = int(db.scalar(count_query) or 0)
        runs = db.scalars(
            query.order_by(PlanningRun.created_at.desc())
            .offset(max(0, (page - 1) * page_size))
            .limit(min(page_size, 100))
        ).all()
        return list(runs), total

    def routes(self, db: Session, run_id: UUID) -> list[PlanningRoute]:
        return list(
            db.scalars(
                select(PlanningRoute)
                .where(PlanningRoute.run_id == run_id)
                .order_by(PlanningRoute.route_index)
            ).all()
        )

    def get_route(self, db: Session, run_id: UUID, route_id: str) -> PlanningRoute:
        route = db.scalar(
            select(PlanningRoute).where(
                PlanningRoute.run_id == run_id,
                PlanningRoute.route_id == route_id,
            )
        )
        if route is None:
            raise PlanningNotFound("Planning route not found.")
        return route

    def rename(self, db: Session, run: PlanningRun, title: str) -> PlanningRun:
        cleaned = title.strip()
        if not cleaned:
            raise PlanningNotEditable("规划标题不能为空")
        run.title = cleaned[:120]
        run.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(run)
        return run

    def delete(self, db: Session, run: PlanningRun) -> None:
        if run.status in {
            PlanningRunStatus.QUEUED.value,
            PlanningRunStatus.RUNNING.value,
        }:
            raise PlanningNotEditable("运行中的规划任务不能删除，请先取消")
        self.risk_grid_file(run.id).unlink(missing_ok=True)
        db.delete(run)
        db.commit()

    def cancel(self, db: Session, run: PlanningRun) -> PlanningRun:
        if run.status == PlanningRunStatus.QUEUED.value:
            run.status = PlanningRunStatus.CANCELLED.value
            run.stage = "cancelled"
            run.finished_at = datetime.now(UTC)
            run.updated_at = datetime.now(UTC)
        elif run.status == PlanningRunStatus.RUNNING.value:
            run.cancel_requested = True
            run.updated_at = datetime.now(UTC)
        else:
            raise PlanningNotCancellable("Only queued or running tasks can be cancelled.")
        db.commit()
        db.refresh(run)
        return run

    def risk_grid_file(self, run_id: UUID) -> Path:
        return self.result_root / f"{run_id}.json.gz"

    def _cleanup_old_runs(self, db: Session) -> None:
        retained = self.settings.planner_max_retained_runs
        old_runs = db.scalars(
            select(PlanningRun)
            .where(
                PlanningRun.status.in_(
                    [
                        PlanningRunStatus.COMPLETED.value,
                        PlanningRunStatus.FAILED.value,
                        PlanningRunStatus.CANCELLED.value,
                    ]
                )
            )
            .order_by(PlanningRun.created_at.desc())
            .offset(retained)
        ).all()
        for run in old_runs:
            self.risk_grid_file(run.id).unlink(missing_ok=True)
            db.delete(run)
        if old_runs:
            db.commit()
