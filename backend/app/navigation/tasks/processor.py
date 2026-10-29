"""Worker-side planning run processor.

All database writes use short sessions; a long optimization never holds an
open write transaction, so cancellation and heartbeats remain responsive.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import UUID

from sqlalchemy import delete

from app.core.config import Settings
from app.models import PlanningRoute, PlanningRun, PlanningRunStatus
from app.navigation.environment.service import EnvironmentService
from app.navigation.planner.dnsga3 import NoFeasibleRoute
from app.navigation.planner.environment_adapter import EnvironmentDataMissing
from app.navigation.planner.errors import PlanningCancelled, PlanningTimeout
from app.navigation.planner.service import PlannerService, PlanningRequest
from app.navigation.vessel.service import VesselService

logger = logging.getLogger("polar_gis.worker.planning")


class PlanningRunProcessor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.worker_id = socket.gethostname()
        self.result_root = Path(settings.planner_result_root)

    def process(self, run_id: UUID, session_factory) -> None:
        run = self._load(session_factory, run_id)
        if run is None:
            return
        started = perf_counter()
        try:
            request = self._parse_request(run)
            planner = PlannerService(
                EnvironmentService(self.settings),
                VesselService(),
                max_search_expansions=self.settings.planner_max_search_expansions,
            )
            deadline = perf_counter() + self.settings.planner_timeout_seconds

            def should_stop() -> bool:
                with session_factory() as db:
                    current = db.get(PlanningRun, run_id)
                    return bool(
                        current is None
                        or current.cancel_requested
                        or current.status == PlanningRunStatus.CANCELLED.value
                    )

            def progress(value: int) -> None:
                progress_value = max(0, min(99, value))
                stage = (
                    "environment"
                    if progress_value < 65
                    else "optimizing"
                    if progress_value < 95
                    else "persisting"
                )
                self._update(
                    session_factory, run_id, progress=progress_value, stage=stage
                )

            if run.mode == "risk_only":
                outcome = planner.risk_only(
                    request,
                    progress=progress,
                    should_stop=should_stop,
                    deadline=deadline,
                )
            else:
                outcome = planner.plan(
                    request,
                    progress=progress,
                    should_stop=should_stop,
                    deadline=deadline,
                )
            risk_path = self._write_risk_grid(run_id, outcome.risk_grid)
            self._persist_outcome(
                session_factory,
                run_id,
                outcome,
                risk_path,
                elapsed_seconds=perf_counter() - started,
            )
        except PlanningCancelled:
            self._finish_cancelled(session_factory, run_id)
        except PlanningTimeout:
            self._finish_failed(
                session_factory,
                run_id,
                "PLANNER_TIMEOUT",
                "Planning exceeded the configured timeout.",
            )
        except EnvironmentDataMissing as error:
            self._finish_failed(
                session_factory,
                run_id,
                "ENVIRONMENT_DATA_MISSING",
                str(error),
                details={"fields": error.fields},
            )
        except NoFeasibleRoute as error:
            self._finish_failed(
                session_factory,
                run_id,
                "NO_FEASIBLE_ROUTE",
                str(error),
            )
        except Exception as error:  # noqa: BLE001 - never kill the only worker
            logger.exception("Planning run %s failed", run_id)
            self._finish_failed(
                session_factory,
                run_id,
                "PLANNER_FAILED",
                f"{type(error).__name__}: {error}",
            )

    def _load(self, session_factory, run_id: UUID) -> PlanningRun | None:
        with session_factory() as db:
            run = db.get(PlanningRun, run_id)
            if run is not None:
                db.expunge(run)
            return run

    def _update(self, session_factory, run_id: UUID, **fields: object) -> None:
        with session_factory() as db:
            run = db.get(PlanningRun, run_id)
            if run is None:
                return
            for key, value in fields.items():
                setattr(run, key, value)
            run.heartbeat_at = datetime.now(UTC)
            db.commit()

    def _parse_request(self, run: PlanningRun) -> PlanningRequest:
        payload = run.request_json or {}
        departure_raw = str(payload.get("departureTime") or payload.get("departure_time"))
        departure = datetime.fromisoformat(departure_raw.replace("Z", "+00:00"))
        if departure.tzinfo is None:
            departure = departure.replace(tzinfo=UTC)
        start = payload.get("start") or {}
        goal = payload.get("goal") or {}
        bbox = payload.get("bbox")
        if (not start or not goal) and bbox and len(bbox) == 4:
            center_lon = (float(bbox[0]) + float(bbox[2])) / 2.0
            center_lat = (float(bbox[1]) + float(bbox[3])) / 2.0
            start = start or {"longitude": center_lon, "latitude": center_lat}
            goal = goal or {"longitude": center_lon, "latitude": center_lat}
        return PlanningRequest(
            start_longitude=float(start["longitude"]),
            start_latitude=float(start["latitude"]),
            goal_longitude=float(goal["longitude"]),
            goal_latitude=float(goal["latitude"]),
            departure=departure,
            vessel_id=run.vessel_id,
            data_policy=run.data_policy,
            population_size=int(payload.get("populationSize", self.settings.planner_population_size)),
            generations=int(payload.get("generations", 20)),
            seed=int(payload.get("seed", 42)),
            bbox=tuple(float(value) for value in bbox) if bbox and len(bbox) == 4 else None,
            synthetic_overrides={
                str(key): float(value)
                for key, value in (payload.get("syntheticOverrides") or {}).items()
            }
            if isinstance(payload.get("syntheticOverrides"), dict)
            else None,
        )

    def _write_risk_grid(self, run_id: UUID, payload: dict[str, object]) -> str:
        self.result_root.mkdir(parents=True, exist_ok=True)
        path = self.result_root / f"{run_id}.json.gz"
        temp = path.with_suffix(".json.gz.tmp")
        with gzip.open(temp, "wt", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, allow_nan=False)
        os.replace(temp, path)
        return path.name

    def _persist_outcome(
        self,
        session_factory,
        run_id: UUID,
        outcome,
        risk_path: str,
        *,
        elapsed_seconds: float,
    ) -> None:
        with session_factory() as db:
            run = db.get(PlanningRun, run_id)
            if run is None:
                return
            if run.worker_id != self.worker_id:
                return  # lease lost to another worker
            if run.cancel_requested or run.status == PlanningRunStatus.CANCELLED.value:
                run.status = PlanningRunStatus.CANCELLED.value
                run.stage = "cancelled"
                run.finished_at = datetime.now(UTC)
                db.commit()
                return
            db.execute(delete(PlanningRoute).where(PlanningRoute.run_id == run_id))
            recommended_route_id = None
            for route in outcome.routes:
                components = route.get("riskComponents") or {}
                db.add(
                    PlanningRoute(
                        run_id=run_id,
                        route_index=int(route["routeIndex"]),
                        route_id=str(route["routeId"]),
                        is_recommended=bool(route["recommended"]),
                        label=str(route["label"]),
                        coordinates_json=route["coordinates"],
                        risk_score=float(route["riskScore"]),
                        ice_risk=components.get("ice"),
                        depth_risk=components.get("depth"),
                        fog_risk=components.get("fog"),
                        wind_risk=components.get("wind"),
                        wave_risk=components.get("wave"),
                        energy_mwh=float(route["energyMWh"]),
                        time_hours=float(route["timeHours"]),
                        distance_km=float(route["distanceKm"]),
                        quality=str(route["sourceQuality"]),
                        algorithm_version=str(route["algorithmVersion"]),
                    )
                )
                if route["recommended"]:
                    recommended_route_id = str(route["routeId"])
            run.risk_grid_path = risk_path
            run.environment_snapshot_json = outcome.snapshot
            run.algorithm_version = outcome.algorithm_version
            run.result_summary_json = {
                "routeCount": len(outcome.routes),
                "recommendedRouteId": recommended_route_id,
                "noRouteReason": outcome.no_route_reason,
                "elapsedSeconds": elapsed_seconds,
                "missingByField": outcome.missing_by_field,
                "requestedStart": outcome.requested_start,
                "requestedGoal": outcome.requested_goal,
                "resolvedStart": outcome.resolved_start,
                "resolvedGoal": outcome.resolved_goal,
            }
            run.progress = 100
            run.finished_at = datetime.now(UTC)
            run.updated_at = datetime.now(UTC)
            if outcome.no_route_reason:
                run.status = PlanningRunStatus.FAILED.value
                run.stage = "failed"
                run.error_code = "NO_FEASIBLE_ROUTE"
                run.error_message = outcome.no_route_reason
            else:
                run.status = PlanningRunStatus.COMPLETED.value
                run.stage = "completed"
            db.commit()

    def _finish_cancelled(self, session_factory, run_id: UUID) -> None:
        with session_factory() as db:
            run = db.get(PlanningRun, run_id)
            if run is None or run.worker_id != self.worker_id:
                return
            run.status = PlanningRunStatus.CANCELLED.value
            run.stage = "cancelled"
            run.finished_at = datetime.now(UTC)
            db.commit()

    def _finish_failed(
        self,
        session_factory,
        run_id: UUID,
        code: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        with session_factory() as db:
            run = db.get(PlanningRun, run_id)
            if run is None or run.worker_id != self.worker_id:
                return
            run.status = PlanningRunStatus.FAILED.value
            run.stage = "failed"
            run.error_code = code
            run.error_message = message
            run.finished_at = datetime.now(UTC)
            if details:
                summary = dict(run.result_summary_json or {})
                summary["errorDetails"] = details
                run.result_summary_json = summary
            db.commit()
