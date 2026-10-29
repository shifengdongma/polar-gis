"""Explicit requested-time vs data-time matching with no future leakage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.navigation.contracts.time import TimeMatchInfo, ensure_utc


@dataclass(frozen=True)
class TimeSelection:
    index: int | None
    requested_time: datetime
    matched_time: datetime | None
    valid_time: datetime | None = None
    issue_time: datetime | None = None
    delta_seconds: float | None = None
    quality: str = "unknown"
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.index is not None and self.matched_time is not None

    def match_info(self, *, policy: str = "latest_not_after") -> TimeMatchInfo:
        return TimeMatchInfo(
            requested_time=self.requested_time,
            matched_time=self.matched_time,
            valid_time=self.valid_time,
            issue_time=self.issue_time,
            match_policy=policy,  # type: ignore[arg-type]
            delta_seconds=self.delta_seconds,
            quality=self.quality,  # type: ignore[arg-type]
        )


def select_time(
    available_times: list[datetime | None],
    requested_time: datetime,
    *,
    max_lag_hours: float | None,
    allow_future: bool = False,
    issue_times: list[datetime | None] | None = None,
    policy: str = "latest_not_after",
) -> TimeSelection:
    """Select a data time for a request.

    ``latest_not_after`` is the safe default: only data valid at or before the
    requested time is eligible, and a file whose issue time is after the
    request is excluded.  ``nearest`` is only for synthetic research.
    """
    requested = ensure_utc(requested_time)
    candidates: list[tuple[int, datetime]] = []
    for index, value in enumerate(available_times):
        if value is None:
            continue
        candidate = ensure_utc(value)
        if issue_times is not None and index < len(issue_times):
            issue = issue_times[index]
            if issue is not None and ensure_utc(issue) > requested:
                continue
        if not allow_future and candidate > requested:
            continue
        candidates.append((index, candidate))

    if not candidates:
        return TimeSelection(
            index=None,
            requested_time=requested,
            matched_time=None,
            reason="no_data_at_or_before_requested_time",
        )

    if policy == "nearest" or allow_future:
        # Research mode may use a future-valid forecast; choose the closest
        # valid time rather than the latest one.
        index, matched = min(
            candidates,
            key=lambda item: (abs((item[1] - requested).total_seconds()), item[1]),
        )
    else:
        index, matched = max(candidates, key=lambda item: item[1])

    delta_seconds = abs((matched - requested).total_seconds())
    if max_lag_hours is not None and delta_seconds > max_lag_hours * 3600.0:
        return TimeSelection(
            index=None,
            requested_time=requested,
            matched_time=matched,
            valid_time=matched,
            issue_time=_issue_at(issue_times, index),
            delta_seconds=delta_seconds,
            reason="matched_time_exceeds_max_lag",
        )

    quality = "exact" if delta_seconds == 0 else "within_tolerance"
    return TimeSelection(
        index=index,
        requested_time=requested,
        matched_time=matched,
        valid_time=matched,
        issue_time=_issue_at(issue_times, index),
        delta_seconds=delta_seconds,
        quality=quality,
    )


def _issue_at(issue_times: list[datetime | None] | None, index: int) -> datetime | None:
    if issue_times is None or index >= len(issue_times):
        return None
    value = issue_times[index]
    return None if value is None else ensure_utc(value)
