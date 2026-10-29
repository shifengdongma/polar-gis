"""Strict timezone-aware UTC time metadata and explicit match semantics."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def ensure_utc(value: datetime) -> datetime:
    """Reject naive datetimes and normalize aware values to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("navigation datetimes must be timezone-aware; naive datetime rejected")
    return value.astimezone(UTC)


class TimeMetadata(BaseModel):
    """Optional source timestamps with explicit meanings, all stored in UTC."""

    model_config = ConfigDict(frozen=True)

    source_time: datetime | None = None
    issue_time: datetime | None = None
    valid_time: datetime | None = None
    observation_time: datetime | None = None
    ingest_time: datetime | None = None

    @field_validator("source_time", "issue_time", "valid_time", "observation_time", "ingest_time")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


TimeMatchPolicy = Literal["exact", "nearest", "latest_not_after"]
TimeMatchQuality = Literal["exact", "within_tolerance", "unknown"]


class TimeMatchInfo(BaseModel):
    """Requested time versus the time actually used for one environment field.

    ``matched_time`` is the provider's chosen data time; ``valid_time`` is the
    time the value is valid for; ``issue_time``/``observation_time``/``ingest_time``
    stay ``None`` when the source does not expose them.  Missing metadata is
    never synthesized.
    """

    model_config = ConfigDict(frozen=True)

    requested_time: datetime
    matched_time: datetime | None = None
    valid_time: datetime | None = None
    issue_time: datetime | None = None
    observation_time: datetime | None = None
    ingest_time: datetime | None = None
    match_policy: TimeMatchPolicy = "latest_not_after"
    delta_seconds: float | None = Field(default=None, ge=0)
    quality: TimeMatchQuality = "unknown"

    @field_validator(
        "requested_time",
        "matched_time",
        "valid_time",
        "issue_time",
        "observation_time",
        "ingest_time",
    )
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


def available_at_decision_time(metadata: TimeMetadata, decision_time: datetime) -> bool | None:
    """Return whether publication/ingest evidence permits use at a decision time.

    ``None`` means neither issue nor ingest time can establish availability.
    """
    decision_utc = ensure_utc(decision_time)
    known_times = (metadata.issue_time, metadata.ingest_time)
    if all(value is None for value in known_times):
        return None
    return all(value is None or value <= decision_utc for value in known_times)


def _delta(later: datetime, earlier: datetime) -> timedelta:
    return ensure_utc(later) - ensure_utc(earlier)


def lead_time(valid_time: datetime, issue_time: datetime) -> timedelta:
    return _delta(valid_time, issue_time)


def data_age(simulation_time: datetime, reference_time: datetime) -> timedelta:
    return _delta(simulation_time, reference_time)


def staleness(simulation_time: datetime, valid_time: datetime) -> timedelta:
    return _delta(simulation_time, valid_time)


def within_max_lag(delta_seconds: float | None, max_lag_hours: float | None) -> bool | None:
    """Return whether a match is within a configured lag.

    ``None`` means no lag policy was supplied; callers must not turn that into
    a safe/unsafe conclusion by accident.
    """
    if max_lag_hours is None:
        return None
    if delta_seconds is None:
        return None
    return delta_seconds <= max_lag_hours * 3600.0
