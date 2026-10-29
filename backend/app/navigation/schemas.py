"""API schemas for navigation environment and vessel endpoints."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.schemas import ApiModel


class TimeMatchRead(ApiModel):
    requested_time: datetime
    matched_time: datetime | None = None
    valid_time: datetime | None = None
    issue_time: datetime | None = None
    observation_time: datetime | None = None
    ingest_time: datetime | None = None
    match_policy: str
    delta_seconds: float | None = None
    quality: str


class FieldObservationRead(ApiModel):
    field: str
    available: bool
    values: dict[str, float | bool | None] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    component_quality: dict[str, str] = Field(default_factory=dict)
    quality: str
    source: str | None = None
    time: TimeMatchRead
    reason: str | None = None
    coverage: dict[str, float] | None = None


class EnvironmentSampleRead(ApiModel):
    longitude: float
    latitude: float
    requested_time: datetime
    data_policy: str
    fields: dict[str, FieldObservationRead]
    quality_summary: str


class EnvironmentQueryRequest(ApiModel):
    longitude: float = Field(ge=-180.0, le=180.0)
    latitude: float = Field(ge=-90.0, le=90.0)
    time: datetime
    fields: list[str] = Field(min_length=1, max_length=5)
    data_policy: Literal["real_only", "allow_synthetic_research"] | None = None


class BatchPointRequest(ApiModel):
    id: str = Field(min_length=1, max_length=80)
    longitude: float = Field(ge=-180.0, le=180.0)
    latitude: float = Field(ge=-90.0, le=90.0)


class BatchQueryRequest(ApiModel):
    time: datetime
    points: list[BatchPointRequest] = Field(min_length=1, max_length=500)
    fields: list[str] = Field(min_length=1, max_length=5)
    data_policy: Literal["real_only", "allow_synthetic_research"] | None = None


class BatchQueryItem(ApiModel):
    id: str
    environment: EnvironmentSampleRead


class BatchQueryResponse(ApiModel):
    results: list[BatchQueryItem]


class FieldQueryRequest(ApiModel):
    field: Literal["wind", "current", "wave"]
    bbox: list[float] = Field(min_length=4, max_length=4)
    time: datetime
    zoom: int = Field(default=3, ge=0, le=18)
    max_points: int = Field(default=600, ge=4, le=900)
    data_policy: Literal["real_only", "allow_synthetic_research"] | None = None


class VectorObservationRead(ApiModel):
    id: str
    longitude: float
    latitude: float
    field: str
    available: bool
    values: dict[str, float | bool | None] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    quality: str
    source: str | None = None
    matched_time: datetime | None = None
    reason: str | None = None


class FieldQueryResponse(ApiModel):
    field: str
    requested_time: datetime
    available: bool
    source: str | None = None
    points: list[VectorObservationRead]
    matched_times: list[datetime] = Field(default_factory=list)
    reason: str | None = None


class EnvironmentSourceRead(ApiModel):
    field: str
    available: bool
    source: str | None = None
    units: dict[str, str] = Field(default_factory=dict)
    coverage: dict[str, float] | None = None
    times: list[datetime] = Field(default_factory=list)
    quality: str
    reason: str | None = None


class VesselSourceRead(ApiModel):
    title: str
    url: str | None = None
    fields: list[str] = Field(default_factory=list)


class VesselRead(ApiModel):
    id: str
    name: str
    vessel_type: str
    operator: str | None = None
    length_m: float
    beam_m: float
    design_draft_m: float
    design_displacement_t: float | None = None
    propulsion_type: str | None = None
    azipod_count: int | None = None
    azipod_power_mw_each: float | None = None
    total_propulsion_power_mw: float
    service_speed_min_kn: float
    service_speed_max_kn: float
    maximum_speed_kn: float
    endurance_nmi: float | None = None
    endurance_days: float | None = None
    ice_class: str | None = None
    continuous_ice_thickness_m: float
    continuous_snow_thickness_m: float | None = None
    continuous_ice_speed_min_kn: float | None = None
    continuous_ice_speed_max_kn: float | None = None
    ukc_m: float
    required_depth_m: float
    sources: list[VesselSourceRead] = Field(default_factory=list)
    live_state_available: bool = False
    live_state_note: str = "未接入实时船位/航向/传感器数据"


class DepthSafetyRead(ApiModel):
    depth_m: float | None
    draft_m: float
    ukc_m: float
    required_depth_m: float
    margin_m: float | None
    status: str
    reason: str | None = None


class PointRead(ApiModel):
    longitude: float
    latitude: float


class PlanningCreateRequest(ApiModel):
    project_id: UUID
    start: PointRead
    goal: PointRead
    departure_time: datetime
    vessel_id: str = Field(min_length=1, max_length=80)
    data_policy: Literal["real_only", "allow_synthetic_research"] = "real_only"
    algorithm: Literal["dnsga3"] = "dnsga3"
    objectives: list[Literal["risk", "energy", "time"]] = Field(
        default_factory=lambda: ["risk", "energy", "time"], min_length=3, max_length=3
    )
    population_size: int = Field(default=36, ge=6, le=120)
    generations: int = Field(default=20, ge=1, le=100)
    seed: int = Field(default=42, ge=0)


class RiskEvaluateRequest(ApiModel):
    project_id: UUID
    bbox: list[float] = Field(min_length=4, max_length=4)
    departure_time: datetime
    vessel_id: str = Field(min_length=1, max_length=80)
    data_policy: Literal["real_only", "allow_synthetic_research"] = "real_only"


class PlanningRunRead(ApiModel):
    plan_id: UUID
    project_id: UUID
    vessel_id: str
    mode: str
    status: str
    stage: str
    progress: int
    data_policy: str
    risk_model_version: str
    algorithm_version: str = ""
    error_code: str | None = None
    error_message: str | None = None
    result_summary: dict[str, Any] = Field(default_factory=dict)
    environment_snapshot: dict[str, Any] = Field(default_factory=dict)
    cancel_requested: bool = False
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class PlanningRouteRead(ApiModel):
    route_id: str
    plan_id: UUID
    route_index: int
    label: str
    recommended: bool
    coordinates: list[list[float]]
    risk_score: float
    risk_components: dict[str, float | None] = Field(default_factory=dict)
    energy_mwh: float
    time_hours: float
    distance_km: float
    source_quality: str
    algorithm_version: str
    created_at: datetime


class EvaluateRouteRequest(ApiModel):
    coordinates: list[list[float]] = Field(min_length=2, max_length=1000)


class EvaluateRouteRead(ApiModel):
    traversable: bool
    risk_score: float | None = None
    energy_mwh: float | None = None
    time_hours: float | None = None
    distance_km: float | None = None
    source_quality: str | None = None
    cell_ids: list[str] = Field(default_factory=list)
    reason: str | None = None
    blocked_cell_id: str | None = None
    snapshot_id: str | None = None
