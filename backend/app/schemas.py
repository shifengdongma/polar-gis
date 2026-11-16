import math
from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
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
    cacheable: bool = False
    render_transport: str = "wms"
    tile_service_url: str | None = None


class MapDatasetConfig(ApiModel):
    id: UUID
    code: str
    name: str
    group_name: str
    sort_order: int
    visible_by_default: bool
    opacity: float
    member_layer_count: int
    data_type: str | None = None


class MapConfig(ApiModel):
    project: ProjectRead
    supported_crs: list[str] = Field(default_factory=lambda: ["EPSG:3857", "EPSG:3413"])
    datasets: list[MapDatasetConfig]


# ── Bulk layer resolve ──────────────────────────────────────────────

class BulkMapLayerResolveRequest(ApiModel):
    dataset_ids: list[UUID] = Field(min_length=1, max_length=100)
    profile: str = Field(min_length=1, max_length=32)
    include_metadata: bool = False


class BulkResolvedLayer(ApiModel):
    id: UUID
    code: str
    name: str
    object_class: str | None = None
    object_name_zh: str | None = None
    geometry_type: str | None = None
    geoserver_workspace: str | None = None
    geoserver_layer_name: str | None = None
    service_url: str
    style_name: str | None = None
    opacity: float = 1.0
    min_zoom: float | None = None
    max_zoom: float | None = None
    extent: list[float] | None = None
    feature_count: int | None = None
    display_category: str
    load_profile: str
    display_priority: int
    recommended: bool
    renderable: bool
    loadable: bool
    style_mapped: bool
    skip_reason: str | None = None
    queryable: bool
    exportable: bool
    group_name: str
    sort_order: int
    # Phase 4: GWC transport and scale hints (all optional, backward-compatible)
    render_transport: str | None = None  # 'gwc_wms' | 'wms'
    tile_service_url: str | None = None
    grid_set: str | None = None
    cacheable: bool = False
    min_scale_denominator: float | None = None
    max_scale_denominator: float | None = None
    render_cost: int | None = None


class BulkResolvedDataset(ApiModel):
    dataset_id: UUID
    dataset_code: str
    dataset_name: str
    version_no: int
    layers: list[BulkResolvedLayer]


class BulkLayerResolveSummary(ApiModel):
    dataset_count: int
    candidate_count: int
    loadable_count: int
    metadata_skipped_count: int
    non_spatial_skipped_count: int
    unavailable_skipped_count: int
    unmapped_style_count: int


class BulkMapLayerResolveResponse(ApiModel):
    datasets: list[BulkResolvedDataset]
    summary: BulkLayerResolveSummary


# ── Map render plan ──────────────────────────────────────────────────


class MapRenderPlanRequest(ApiModel):
    layer_ids: list[UUID] = Field(min_length=0, max_length=160)
    profile: str = Field(min_length=1, max_length=32)
    projection: str = Field(default="EPSG:3857", pattern=r"^EPSG:\d+$")
    render_mode: str = Field(default="smart")
    view_extent: list[float] | None = None
    zoom: int | None = None


class BundleConfigOut(ApiModel):
    bundle_id: str
    bucket: str
    layer_ids: list[UUID]
    layer_names: list[str]
    styles: list[str]
    z_index: int
    opacity: float
    extent: list[float] | None = None
    min_zoom: int | None = None
    max_zoom: int | None = None
    transport: str = "wms_multi"
    service_url: str = "/geoserver/polar_gis/wms"
    cache_key: str


class StandaloneConfigOut(ApiModel):
    layer_id: UUID
    layer_name: str
    style: str
    z_index: int
    opacity: float
    reason: str  # "custom_opacity" | "render_standalone"


class RenderPlanSummaryOut(ApiModel):
    logical_layer_count: int = 0
    bundle_count: int = 0
    standalone_count: int = 0
    estimated_request_reduction_ratio: float = 0.0


class MapRenderPlanResponse(ApiModel):
    generation: str
    bundles: list[BundleConfigOut]
    standalone_layers: list[StandaloneConfigOut]
    summary: RenderPlanSummaryOut


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
    purpose: str = "standard"
    metadata_json: dict[str, Any] = Field(default_factory=dict)
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
    details: dict[str, Any] = Field(default_factory=dict)
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


class S57WaterwayLayerRead(ApiModel):
    id: str
    name: str
    code: str
    dataset_code: str
    dataset_name: str
    version_no: int
    source_cell: str | None = None
    feature_count: int | None = None
    queryable: bool
    renderable: bool
    available: bool
    reason: str | None = None


class S57WaterwayClassRead(ApiModel):
    code: str
    name_zh: str
    group: str
    group_name_zh: str
    auxiliary: bool
    default_selected: bool
    description: str
    count: int
    layer_count: int
    queryable: bool
    renderable: bool
    layers: list[S57WaterwayLayerRead] = Field(default_factory=list)


class S57WaterwayCatalogRead(ApiModel):
    classes: list[S57WaterwayClassRead]
    total: int
    count_complete: bool
    truncated: bool
    searchable_layer_count: int = 0
    linked_cell_count: int = 0
    candidate_layer_count: int = 0
    resolved_layer_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class S57WaterwayFilterRequest(ApiModel):
    keyword: str | None = Field(default=None, max_length=200)
    object_classes: list[str] = Field(default_factory=list, max_length=50)
    include_auxiliary: bool = False
    bbox: tuple[float, float, float, float] | None = None
    source_cells: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("keyword")
    @classmethod
    def strip_keyword(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("bbox")
    @classmethod
    def validate_bbox(
        cls, value: tuple[float, float, float, float] | None
    ) -> tuple[float, float, float, float] | None:
        if value is None:
            return None
        xmin, ymin, xmax, ymax = value
        if not all(math.isfinite(item) for item in value):
            raise ValueError("bbox 必须是有限数值")
        if not (-180 <= xmin <= 180 and -180 <= xmax <= 180):
            raise ValueError("bbox 经度必须在 -180..180")
        if not (-90 <= ymin < ymax <= 90):
            raise ValueError("bbox 纬度必须满足 -90 <= ymin < ymax <= 90")
        # xmin > xmax is allowed and interpreted as crossing the antimeridian.
        return value


class S57WaterwaySearchRequest(S57WaterwayFilterRequest):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)


class S57WaterwaySnapshotCreateRequest(S57WaterwayFilterRequest):
    name: str | None = Field(default=None, max_length=120)
    max_features: int | None = Field(default=None, ge=1, le=100000)


class S57WaterwayPreviewRequest(S57WaterwayFilterRequest):
    max_features: int | None = Field(default=None, ge=1, le=10000)
    class_cursors: dict[str, str] | None = None


class S57WaterwaySearchItem(ApiModel):
    id: str
    layer_id: str
    layer_name: str
    layer_code: str
    dataset_code: str
    dataset_name: str
    version_no: int
    source_cell: str | None = None
    object_class: str
    object_name_zh: str
    group: str
    group_name_zh: str
    auxiliary: bool
    name: str | None = None
    name_field: str | None = None
    inform: str | None = None
    status: str | None = None
    geometry_type: str | None = None
    renderable: bool
    geometry: dict[str, Any] | None = None
    bbox: list[float] | None = None


class S57WaterwaySearchResponse(ApiModel):
    items: list[S57WaterwaySearchItem]
    page: int
    page_size: int
    total: int
    truncated_layers: bool
    warnings: list[str] = Field(default_factory=list)


class S57WaterwayPreviewResponse(ApiModel):
    items: list[S57WaterwaySearchItem] = Field(default_factory=list)
    total: int
    truncated: bool = False
    matched_total: int | None = None
    returned_count: int = 0
    has_more: bool = False
    class_has_more: dict[str, bool] = Field(default_factory=dict)
    next_cursors: dict[str, str] = Field(default_factory=dict)
    class_matched_totals: dict[str, int | None] = Field(default_factory=dict)
    count_complete: bool = True
    truncated_layers: bool = False
    group_counts: dict[str, int] = Field(default_factory=dict)
    object_class_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class S57WaterwayDiagnosticsTotals(ApiModel):
    linked_cell_count: int = 0
    waterway_layer_count: int = 0
    searchable_layer_count: int = 0
    renderable_layer_count: int = 0
    feature_count: int = 0
    count_complete: bool = True
    candidate_layer_count: int = 0
    resolved_layer_count: int = 0
    catalog_truncated: bool = False
    layer_warning_threshold: int = 500


class S57WaterwayDiagnosticsCell(ApiModel):
    source_cell: str
    dataset_codes: list[str] = Field(default_factory=list)
    dataset_names: list[str] = Field(default_factory=list)
    version_nos: list[int] = Field(default_factory=list)
    layer_count: int = 0
    waterway_layer_count: int = 0
    searchable_layer_count: int = 0
    renderable_layer_count: int = 0
    feature_count: int = 0
    waterway_feature_count: int = 0
    count_complete: bool = True
    object_classes: list[str] = Field(default_factory=list)
    waterway_classes: list[str] = Field(default_factory=list)
    bbox: list[float] | None = None
    coverage_source: str = "unknown"
    coverage_verified: bool = False
    reasons: list[str] = Field(default_factory=list)


class S57WaterwayDiagnosticsRegion(ApiModel):
    code: str
    name_zh: str
    approximate_bbox: list[list[float]] = Field(default_factory=list)
    status: str
    cells: list[str] = Field(default_factory=list)
    waterway_classes: list[str] = Field(default_factory=list)
    feature_count: int = 0
    count_complete: bool = True
    note: str = ""


class S57WaterwayDiagnosticsRead(ApiModel):
    project_id: str
    generated_at: str
    totals: S57WaterwayDiagnosticsTotals
    cells: list[S57WaterwayDiagnosticsCell] = Field(default_factory=list)
    classes: list[S57WaterwayClassRead] = Field(default_factory=list)
    regions: list[S57WaterwayDiagnosticsRegion] = Field(default_factory=list)
    northeast_passage: dict[str, Any] = Field(default_factory=dict)
    references: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checked_at: str


class S57ThematicLayerRead(ApiModel):
    id: str
    name: str
    code: str
    dataset_code: str
    dataset_name: str
    version_no: int
    source_cell: str | None = None
    feature_count: int | None = None
    queryable: bool
    renderable: bool
    available: bool
    extractable: bool
    geometry_type: str | None = None
    reason: str | None = None


class S57ThematicClassRead(ApiModel):
    code: str
    name_zh: str
    category: str
    category_name_zh: str
    description: str
    caveats: list[str] = Field(default_factory=list)
    default_selected: bool = False
    count: int = 0
    count_complete: bool = True
    layer_count: int = 0
    queryable: bool = False
    renderable: bool = False
    extractable: bool = False
    layers: list[S57ThematicLayerRead] = Field(default_factory=list)


class S57ThematicCategoryRead(ApiModel):
    code: str
    name_zh: str
    classes: list[S57ThematicClassRead] = Field(default_factory=list)


class S57ThematicCatalogRead(ApiModel):
    categories: list[S57ThematicCategoryRead] = Field(default_factory=list)
    classes: list[S57ThematicClassRead] = Field(default_factory=list)
    total_layer_count: int = 0
    extractable_layer_count: int = 0
    feature_count: int = 0
    count_complete: bool = True
    candidate_layer_count: int = 0
    resolved_layer_count: int = 0
    cells: list[dict[str, Any]] = Field(default_factory=list)
    datasets: list[dict[str, Any]] = Field(default_factory=list)
    soundg_depth: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    semantics: list[str] = Field(default_factory=list)


class S57ThematicExportCreateRequest(ApiModel):
    name: str | None = Field(default=None, max_length=120)
    object_classes: list[str] = Field(min_length=1, max_length=100)
    bbox: tuple[float, float, float, float] | None = None
    source_cells: list[str] = Field(default_factory=list, max_length=100)
    dataset_ids: list[UUID] = Field(default_factory=list, max_length=100)
    max_features_per_class: int | None = Field(default=None, ge=1, le=1000000)

    @field_validator("object_classes")
    @classmethod
    def strip_object_classes(cls, value: list[str]) -> list[str]:
        normalized = [
            item.rsplit(":", maxsplit=1)[-1].strip().upper()
            for item in value
            if item.strip()
        ]
        if not normalized:
            raise ValueError("请至少选择一个 S-57 对象类")
        return list(dict.fromkeys(normalized))

    @field_validator("bbox")
    @classmethod
    def validate_bbox(
        cls, value: tuple[float, float, float, float] | None
    ) -> tuple[float, float, float, float] | None:
        if value is None:
            return None
        xmin, ymin, xmax, ymax = value
        if not all(math.isfinite(item) for item in value):
            raise ValueError("bbox 必须是有限数值")
        if not (-180 <= xmin <= 180 and -180 <= xmax <= 180):
            raise ValueError("bbox 经度必须在 -180..180")
        if not (-90 <= ymin < ymax <= 90):
            raise ValueError("bbox 纬度必须满足 -90 <= ymin < ymax <= 90")
        return value


class S57ThematicExportClassStat(ApiModel):
    code: str
    name_zh: str
    category: str
    category_name_zh: str
    feature_count: int = 0
    truncated: bool = False
    layer_count: int = 0


class S57ThematicExportFileRead(ApiModel):
    path: str
    object_class: str
    source_cell: str | None = None
    layer_id: str
    feature_count: int
    sha256: str
    bytes: int
    part: int = 1


class S57ThematicExportPreviewRead(ApiModel):
    path: str
    feature_count: int
    sha256: str
    sample: bool = True


class S57ThematicExportManifest(ApiModel):
    schema_version: str
    export_id: str
    project_id: str
    name: str
    created_at: str
    crs: str = "EPSG:4326"
    categories: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    bbox: list[float] | None = None
    feature_count: int = 0
    feature_count_unit: str | None = None
    complete: bool = True
    truncated: bool = False
    truncation_reasons: list[str] = Field(default_factory=list)
    object_classes: list[S57ThematicExportClassStat] = Field(default_factory=list)
    class_counts: dict[str, int] = Field(default_factory=dict)
    cell_counts: dict[str, int] = Field(default_factory=dict)
    files: list[S57ThematicExportFileRead] = Field(default_factory=list)
    source_datasets: list[dict[str, Any]] = Field(default_factory=list)
    source_version_ids: list[str] = Field(default_factory=list)
    source_content_hashes: dict[str, str] = Field(default_factory=dict)
    source_cells: list[str] = Field(default_factory=list)
    skipped_layers: list[dict[str, Any]] = Field(default_factory=list)
    depth: dict[str, Any] = Field(default_factory=dict)
    preview: S57ThematicExportPreviewRead | None = None
    semantics: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    stale: bool = False


class S57ThematicExportList(ApiModel):
    items: list[S57ThematicExportManifest] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class S57WaterwayPropertyRead(ApiModel):
    field: str
    label_zh: str
    raw: Any = None
    provided: bool
    description: str | None = None
    source: str | None = None


class S57WaterwayDetailRead(ApiModel):
    id: str
    layer_id: str
    layer_name: str
    layer_code: str
    dataset_code: str
    dataset_name: str
    version_no: int
    source_cell: str | None = None
    object_class: str
    object_name_zh: str
    group: str
    group_name_zh: str
    auxiliary: bool
    name: str | None = None
    name_field: str | None = None
    geometry_type: str | None = None
    geometry: dict[str, Any] | None = None
    bbox: list[float] | None = None
    updated_at: str | None = None
    properties: list[S57WaterwayPropertyRead] = Field(default_factory=list)
    raw_properties: dict[str, Any] = Field(default_factory=dict)


class S57WaterwaySnapshotSource(ApiModel):
    dataset_id: str
    dataset_code: str
    dataset_name: str
    version_id: str | None = None
    version_no: int
    source_cell: str | None = None
    layer_ids: list[str] = Field(default_factory=list)
    content_hash: str | None = None


class S57WaterwaySnapshotManifest(ApiModel):
    snapshot_id: str
    project_id: str
    name: str
    created_at: str
    crs: str
    feature_count: int
    truncated: bool = False
    object_classes: list[str] = Field(default_factory=list)
    source_datasets: list[S57WaterwaySnapshotSource] = Field(default_factory=list)
    source_version_ids: list[str] = Field(default_factory=list)
    source_content_hashes: dict[str, str] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    schema_version: str
    warnings: list[str] = Field(default_factory=list)
    geojson_sha256: str | None = None
    stale: bool = False


class S57WaterwaySnapshotList(ApiModel):
    items: list[S57WaterwaySnapshotManifest] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExportRequest(ApiModel):
    format: str = Field(pattern=r"^(csv|geojson)$")
    filters: list[FeatureFilter] = Field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    fields: list[str] = Field(default_factory=list)


class WeatherPointRequest(ApiModel):
    coordinate: tuple[float, float]
    crs: str = "EPSG:4326"


class IceFieldRead(ApiModel):
    id: str
    name: str
    label: str
    units: str
    available: bool = True
    # 字段在哪些日期真实存在(时间轴/开关禁用态的唯一依据;不自动补日期)
    available_dates: list[str] = Field(default_factory=list)


class IceInfoRead(ApiModel):
    dates: list[str] = Field(default_factory=list)
    fields: list[IceFieldRead] = Field(default_factory=list)
    default_date: str | None = None
    source: str = "netcdf"
    source_crs: str = "EPSG:3411"
    # 源网格(EPSG:3411 米)范围,前端经 WGS84 重投影到当前显示投影
    extent: tuple[float, float, float, float] | None = None
    missing_dates_are_excluded: bool = True


class IceValueRead(ApiModel):
    # value 保持首字段:miss 的响应体精确为 {"value": null}
    # (路由以 response_model_exclude_unset=True 仅输出已设置的字段)
    value: float | None = None
    date: str | None = None
    field: str | None = None
    units: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    source_x: float | None = None
    source_y: float | None = None


T = TypeVar("T")


class Paginated(ApiModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int
