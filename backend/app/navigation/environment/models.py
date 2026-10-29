"""Internal environment contracts (point, vector, source, snapshot)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.navigation.contracts import DataQuality, TimeMatchInfo

EnvironmentField = Literal["bathymetry", "ice", "wind", "current", "wave"]
DataPolicy = Literal["real_only", "allow_synthetic_research"]


class ProviderSample(BaseModel):
    """Raw provider result before service-level policy/quality wrapping."""

    model_config = ConfigDict(frozen=True)

    available: bool
    values: dict[str, float | bool | None] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    component_quality: dict[str, DataQuality] = Field(default_factory=dict)
    source: str | None = None
    time: TimeMatchInfo
    reason: str | None = None
    coverage: dict[str, float] | None = None


class FieldObservation(BaseModel):
    """One field at one WGS84 point and one requested time."""

    model_config = ConfigDict(frozen=True)

    field: EnvironmentField
    available: bool
    values: dict[str, float | bool | None] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    component_quality: dict[str, DataQuality] = Field(default_factory=dict)
    quality: DataQuality = DataQuality.MISSING
    source: str | None = None
    time: TimeMatchInfo
    reason: str | None = None
    coverage: dict[str, float] | None = None


class EnvironmentSample(BaseModel):
    """Fault-isolated multi-field result for one point."""

    model_config = ConfigDict(frozen=True)

    longitude: float
    latitude: float
    requested_time: datetime
    data_policy: DataPolicy
    fields: dict[str, FieldObservation]
    quality_summary: DataQuality


class VectorObservation(BaseModel):
    """One sampled vector/field point for map overlays."""

    model_config = ConfigDict(frozen=True)

    id: str
    longitude: float
    latitude: float
    field: EnvironmentField
    available: bool
    values: dict[str, float | bool | None] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    quality: DataQuality
    source: str | None = None
    matched_time: datetime | None = None
    reason: str | None = None


class EnvironmentSourceInfo(BaseModel):
    """Availability and provenance of one provider."""

    model_config = ConfigDict(frozen=True)

    field: EnvironmentField
    available: bool
    source: str | None = None
    units: dict[str, str] = Field(default_factory=dict)
    coverage: dict[str, float] | None = None
    times: list[datetime] = Field(default_factory=list)
    quality: DataQuality = DataQuality.MISSING
    reason: str | None = None


class FieldSnapshotInfo(BaseModel):
    """Per-field metadata frozen into a planning run."""

    model_config = ConfigDict(frozen=True)

    field: EnvironmentField
    available: bool
    source: str | None = None
    quality: DataQuality
    units: dict[str, str] = Field(default_factory=dict)
    matched_time: datetime | None = None
    valid_time: datetime | None = None
    issue_time: datetime | None = None
    reason: str | None = None


class EnvironmentSnapshot(BaseModel):
    """Explicit environment time/provenance context for a planning run."""

    model_config = ConfigDict(frozen=True)

    requested_time: datetime
    data_policy: DataPolicy
    quality_summary: DataQuality
    fields: dict[str, FieldSnapshotInfo]
