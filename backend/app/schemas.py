from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.models import DatasetType, ProjectStatus, Role


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class LoginRequest(ApiModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)


class AccessTokenResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class UserCreate(ApiModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_.@-]+$", min_length=3, max_length=120)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=256)
    role: Role = Role.USER


class UserUpdate(ApiModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: Role | None = None
    is_active: bool | None = None


class PasswordReset(ApiModel):
    password: str = Field(min_length=8, max_length=256)


class UserRead(ApiModel):
    id: UUID
    username: str
    display_name: str
    role: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class ProjectCreate(ApiModel):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$", min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=4000)
    default_crs: str = Field(default="EPSG:3857", pattern=r"^EPSG:\d+$")
    initial_extent: str | None = None


class ProjectUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    default_crs: str | None = Field(default=None, pattern=r"^EPSG:\d+$")
    initial_extent: str | None = None


class ProjectRead(ApiModel):
    id: UUID
    code: str
    name: str
    description: str
    status: ProjectStatus
    default_crs: str
    initial_extent: str | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    layer_count: int = 0


class ProjectLayerInput(ApiModel):
    layer_id: UUID
    style_id: UUID | None = None
    group_name: str = Field(default="默认分组", max_length=120)
    sort_order: int = 0
    visible_by_default: bool = False
    opacity: float = Field(default=1, ge=0, le=1)
    min_zoom: float | None = None
    max_zoom: float | None = None


class ProjectLayersUpdate(ApiModel):
    layers: list[ProjectLayerInput]


class ProjectLayerConfigRead(ProjectLayerInput):
    id: UUID


class ProjectDatasetLayerInput(ApiModel):
    dataset_id: UUID
    group_name: str = Field(default="默认分组", max_length=120)
    sort_order: int = 0
    visible_by_default: bool = False
    opacity: float = Field(default=1, ge=0, le=1)


class ProjectDatasetLayersUpdate(ApiModel):
    datasets: list[ProjectDatasetLayerInput]


class ProjectDatasetLayerRead(ProjectDatasetLayerInput):
    dataset_code: str
    dataset_name: str
    data_type: str
    version_no: int
    available_layer_count: int
    selected: bool = False


class MapLayerConfig(ApiModel):
    id: UUID
    code: str
    name: str
    group_name: str
    sort_order: int
    visible_by_default: bool
    opacity: float
    queryable: bool
    exportable: bool
    service_type: str = "WMS"
    service_url: str
    service_layer_name: str
    style_name: str | None = None
    geometry_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MapDatasetConfig(ApiModel):
    id: UUID
    code: str
    name: str
    group_name: str
    sort_order: int
    visible_by_default: bool
    opacity: float
    member_layer_count: int


class MapConfig(ApiModel):
    project: ProjectRead
    supported_crs: list[str] = Field(default_factory=lambda: ["EPSG:3857", "EPSG:3413"])
    datasets: list[MapDatasetConfig]


class UploadRead(ApiModel):
    id: UUID
    original_name: str
    size_bytes: int
    sha256: str
    media_type: str | None
    created_at: datetime


class DatasetCreate(ApiModel):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$", min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=180)
    data_type: DatasetType
    upload_id: UUID
    source_crs: str | None = None
    description: str = Field(default="", max_length=4000)


class S57UpdateCreate(ApiModel):
    upload_id: UUID


class DatasetRead(ApiModel):
    id: UUID
    code: str
    name: str
    data_type: str
    description: str
    current_version_id: UUID | None
    created_at: datetime
    updated_at: datetime
    version_count: int = 0


class DatasetVersionRead(ApiModel):
    id: UUID
    dataset_id: UUID
    version_no: int
    source_format: str
    source_crs: str | None
    status: str
    content_hash: str
    metadata_json: dict[str, Any]
    created_at: datetime
    activated_at: datetime | None


class DatasetProjectReferenceRead(ApiModel):
    id: UUID
    code: str
    name: str
    status: str


class DatasetCleanupPreview(ApiModel):
    dataset_id: UUID
    dataset_code: str
    dataset_name: str
    deleted_at: datetime
    confirmation_text: str
    source_files: list[str]
    derived_tables: list[str]
    geoserver_resources: list[str]
    version_count: int
    layer_count: int


class DatasetPurgeRequest(ApiModel):
    confirmation: str = Field(min_length=1, max_length=120)


class DatasetBulkDeleteRequest(ApiModel):
    dataset_ids: list[UUID] = Field(min_length=1, max_length=1000)


class DatasetBulkDeleteBlocked(ApiModel):
    dataset_id: UUID
    dataset_name: str
    projects: list[DatasetProjectReferenceRead]


class DatasetBulkDeleteResult(ApiModel):
    deleted_ids: list[UUID]
    blocked: list[DatasetBulkDeleteBlocked]


class DatasetBulkPurgePreviewRequest(ApiModel):
    dataset_ids: list[UUID] = Field(min_length=1, max_length=1000)


class DatasetBulkPurgePreview(ApiModel):
    confirmation_text: str
    datasets: list[DatasetCleanupPreview]


class DatasetBulkPurgeRequest(DatasetBulkPurgePreviewRequest):
    confirmation: str = Field(min_length=1, max_length=120)


class DatasetBulkPurgeResult(ApiModel):
    purged_ids: list[UUID]


class ImportJobRead(ApiModel):
    id: UUID
    dataset_id: UUID
    dataset_version_id: UUID
    job_type: str
    status: str
    stage: str
    progress: int
    attempt: int
    error_code: str | None
    error_message: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class S57ImportBatchRead(ApiModel):
    id: UUID
    name: str
    status: str
    stage: str
    progress: int
    total_cells: int
    processed_cells: int
    succeeded_cells: int
    failed_cells: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class S57ImportBatchItemRead(ApiModel):
    id: UUID
    batch_id: UUID
    cell_name: str
    status: str
    stage: str
    progress: int
    update_count: int
    current_update: int
    dataset_id: UUID | None
    error_code: str | None
    error_message: str | None
    finished_at: datetime | None


class S57ImportBatchDetail(S57ImportBatchRead):
    items: list[S57ImportBatchItemRead]


class LayerRead(ApiModel):
    id: UUID
    dataset_version_id: UUID
    code: str
    name: str
    geometry_type: str | None
    source_crs: str | None
    status: str
    queryable: bool
    exportable: bool
    allowed_fields: list[str]
    metadata_json: dict[str, Any]


class LayerUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    queryable: bool | None = None
    exportable: bool | None = None
    allowed_fields: list[str] | None = None


class BaseMapCreate(ApiModel):
    name: str = Field(min_length=1, max_length=180)
    map_type: str = Field(pattern=r"^(XYZ|WMTS)$")
    url_template: str = Field(min_length=1, max_length=1000)
    crs: str = Field(default="EPSG:3857", pattern=r"^EPSG:\d+$")
    attribution: str = Field(default="", max_length=500)
    is_offline: bool = False
    is_enabled: bool = True


class BaseMapRead(BaseMapCreate):
    id: UUID
    created_at: datetime


class StyleCreate(ApiModel):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$", min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=180)
    upload_id: UUID


class StyleRead(ApiModel):
    id: UUID
    code: str
    name: str
    geoserver_style_name: str | None
    status: str
    created_at: datetime


class AuditLogRead(ApiModel):
    id: UUID
    user_id: UUID | None
    username: str | None
    role: str | None
    action: str
    resource_type: str
    resource_id: str | None
    result: str
    request_id: str | None
    changes: dict[str, Any]
    created_at: datetime


class IdentifyRequest(ApiModel):
    coordinate: tuple[float, float]
    crs: str = "EPSG:4326"
    tolerance: float = Field(default=8, ge=0, le=100)
    resolution: float | None = Field(default=None, gt=0)


class FeatureFilter(ApiModel):
    field: str
    operator: str
    value: Any


class FeatureSearchRequest(ApiModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)
    filters: list[FeatureFilter] = Field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    bbox_crs: str = "EPSG:4326"


class ExportRequest(ApiModel):
    format: str = Field(pattern=r"^(csv|geojson)$")
    filters: list[FeatureFilter] = Field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    fields: list[str] = Field(default_factory=list)


class WeatherPointRequest(ApiModel):
    coordinate: tuple[float, float]
    crs: str = "EPSG:4326"


T = TypeVar("T")


class Paginated(ApiModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int
