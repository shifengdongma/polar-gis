from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_admin
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models import (
    Dataset,
    DatasetType,
    DatasetVersion,
    Layer,
    LayerStatus,
    Project,
    ProjectLayer,
    ProjectStatus,
    Style,
    User,
)
from app.schemas import (
    BulkLayerResolveSummary,
    BulkMapLayerResolveRequest,
    BulkMapLayerResolveResponse,
    BulkResolvedDataset,
    BulkResolvedLayer,
    BundleConfigOut,
    MapConfig,
    MapDatasetConfig,
    MapLayerConfig,
    MapRenderPlanRequest,
    MapRenderPlanResponse,
    Paginated,
    ProjectCreate,
    ProjectDatasetLayerRead,
    ProjectDatasetLayersUpdate,
    ProjectLayerConfigRead,
    ProjectLayersUpdate,
    ProjectRead,
    ProjectUpdate,
    RenderPlanSummaryOut,
    StandaloneConfigOut,
)
from app.services.audit import write_audit
from app.services.map_render_plan import (
    LayerRenderInput,
    build_bundles,
    bundle_cache_key,
)
from app.services.s57_layer_catalog import classify_s57_layer
from app.services.s57_styles import preset_for_object_class

public_router = APIRouter(prefix="/projects", tags=["projects"])
admin_router = APIRouter(prefix="/admin/projects", tags=["admin-projects"])
settings = get_settings()


def project_to_read(project: Project) -> ProjectRead:
    dataset_ids = {
        link.layer.dataset_version.dataset_id
        for link in project.project_layers
        if link.layer is not None and link.layer.dataset_version is not None
    }
    return ProjectRead.model_validate(project).model_copy(update={"layer_count": len(dataset_ids)})


def project_load_options() -> list:
    return [
        selectinload(Project.project_layers)
        .selectinload(ProjectLayer.layer)
        .selectinload(Layer.dataset_version)
    ]


def project_or_404(db: Session, project_id: UUID, include_unpublished: bool = True) -> Project:
    statement = (
        select(Project)
        .where(Project.id == project_id, Project.deleted_at.is_(None))
        .options(*project_load_options())
    )
    if not include_unpublished:
        statement = statement.where(Project.status == ProjectStatus.PUBLISHED.value)
    project = db.scalar(statement)
    if project is None:
        raise AppError("PROJECT_NOT_FOUND", "项目不存在或无权访问", 404)
    return project


@public_router.get("", response_model=Paginated[ProjectRead])
def list_projects(
    search: str | None = None,
    order: str = "desc",
    page: int = 1,
    page_size: int = 15,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Paginated[ProjectRead]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    conditions = [Project.status == ProjectStatus.PUBLISHED.value, Project.deleted_at.is_(None)]
    if search:
        conditions.append(Project.name.ilike(f"%{search}%"))
    total = db.scalar(select(func.count()).select_from(Project).where(*conditions)) or 0
    sort_column = Project.created_at.asc() if order == "asc" else Project.created_at.desc()
    projects = db.scalars(
        select(Project)
        .where(*conditions)
        .options(*project_load_options())
        .order_by(sort_column)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Paginated(
        items=[project_to_read(project) for project in projects],
        page=page,
        page_size=page_size,
        total=total,
    )


@public_router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ProjectRead:
    return project_to_read(project_or_404(db, project_id, include_unpublished=False))


@public_router.get("/{project_id}/map-config", response_model=MapConfig)
def get_map_config(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> MapConfig:
    project = project_or_404(db, project_id, include_unpublished=False)
    links = db.scalars(
        select(ProjectLayer)
        .where(ProjectLayer.project_id == project.id)
        .options(
            selectinload(ProjectLayer.layer)
            .selectinload(Layer.dataset_version)
            .selectinload(DatasetVersion.dataset),
            selectinload(ProjectLayer.style),
        )
        .order_by(ProjectLayer.sort_order)
    ).all()
    grouped_links: dict[UUID, list[ProjectLayer]] = {}
    for link in links:
        layer = link.layer
        if (
            layer.status != LayerStatus.AVAILABLE.value
            or layer.deleted_at is not None
            or layer.dataset_version.dataset.current_version_id != layer.dataset_version_id
        ):
            continue
        grouped_links.setdefault(layer.dataset_version.dataset_id, []).append(link)
    dataset_configs = []
    for dataset_links in grouped_links.values():
        first_link = dataset_links[0]
        first_layer = first_link.layer
        dataset = first_layer.dataset_version.dataset
        dataset_configs.append(
            MapDatasetConfig(
                id=dataset.id,
                code=dataset.code,
                name=dataset.name,
                group_name=first_link.group_name,
                sort_order=first_link.sort_order,
                visible_by_default=first_link.visible_by_default,
                opacity=float(first_link.opacity),
                member_layer_count=len(dataset_links),
                data_type=dataset.data_type,
            )
        )
    return MapConfig(project=project_to_read(project), datasets=dataset_configs)


@public_router.get("/{project_id}/map-datasets/{dataset_id}/layers", response_model=list[MapLayerConfig])
def get_project_dataset_map_layers(
    project_id: UUID,
    dataset_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[MapLayerConfig]:
    project = project_or_404(db, project_id, include_unpublished=False)
    links = db.scalars(
        select(ProjectLayer)
        .join(Layer, ProjectLayer.layer_id == Layer.id)
        .join(DatasetVersion, Layer.dataset_version_id == DatasetVersion.id)
        .join(Dataset, DatasetVersion.dataset_id == Dataset.id)
        .where(
            ProjectLayer.project_id == project.id,
            DatasetVersion.dataset_id == dataset_id,
            Dataset.current_version_id == Layer.dataset_version_id,
            Dataset.deleted_at.is_(None),
            Layer.status == LayerStatus.AVAILABLE.value,
            Layer.deleted_at.is_(None),
        )
        .options(selectinload(ProjectLayer.layer), selectinload(ProjectLayer.style))
        .order_by(ProjectLayer.sort_order)
    ).all()
    if not links:
        raise AppError("PROJECT_DATASET_NOT_FOUND", "项目未配置该数据集", 404)
    configs: list[MapLayerConfig] = []
    for link in links:
        cacheable, render_transport, tile_service_url = _gwc_transport_for_layer(link.layer)
        workspace = link.layer.geoserver_workspace or settings.geoserver_workspace
        layer_name = link.layer.geoserver_layer_name or link.layer.code
        style_name = link.style.geoserver_style_name if link.style else None
        # Emit workspace-qualified names ("ws:layer" / "ws:style"): the GWC
        # WMS facade matches layer/style names exactly against its registry
        # and rejects bare names with 400, while GeoServer's own WMS resolves
        # them via the default namespace.  Same contract as the render-plan
        # path (see _build_layer_render_input).
        configs.append(
            MapLayerConfig(
                id=link.layer.id,
                code=link.layer.code,
                name=link.layer.name,
                group_name=link.group_name,
                sort_order=link.sort_order,
                visible_by_default=link.visible_by_default,
                opacity=float(link.opacity),
                queryable=link.layer.queryable,
                exportable=link.layer.exportable,
                service_url=(
                    f"{settings.geoserver_public_url.rstrip('/')}"
                    f"/{workspace}/wms"
                ),
                service_layer_name=f"{workspace}:{layer_name}" if layer_name else layer_name,
                style_name=f"{workspace}:{style_name}" if style_name else None,
                geometry_type=link.layer.geometry_type,
                metadata=link.layer.metadata_json,
                cacheable=cacheable,
                render_transport=render_transport,
                tile_service_url=tile_service_url,
            )
        )
    return configs


# ── Resolve helpers ──────────────────────────────────────────────────

VALID_RESOLVE_PROFILES = frozenset({"core_chart", "navigation_recommended", "all_spatial"})
MAX_RESOLVE_DATASET_IDS = 100


def _s57_object_class(layer: Layer) -> str:
    """Extract the S-57 object class from layer metadata, with fallbacks."""
    s57_meta = (layer.metadata_json or {}).get("s57")
    if isinstance(s57_meta, dict) and s57_meta.get("objectClass"):
        return str(s57_meta["objectClass"])
    source = (layer.metadata_json or {}).get("sourceLayer")
    if source and isinstance(source, str) and source.strip():
        return source.strip()
    return layer.name or layer.code


def _style_mapped_for_layer(layer: Layer) -> bool:
    """Check if layer has a mapped S-57 style."""
    s57_meta = (layer.metadata_json or {}).get("s57")
    if isinstance(s57_meta, dict) and "styleMapped" in s57_meta:
        return bool(s57_meta["styleMapped"])
    status = (layer.metadata_json or {}).get("s57StyleStatus")
    if status == "mapped":
        return True
    if status == "unmapped":
        return False
    return preset_for_object_class(_s57_object_class(layer)) is not None


def _gwc_transport_for_layer(
    layer: Layer,
    rule: object | None = None,
) -> tuple[bool, str, str]:
    """Compute GWC transport classification for a layer.

    Returns ``(cacheable, render_transport, tile_service_url)`` with the same
    semantics as the resolve endpoint: core/navigation layers published to
    GeoServer are cacheable and rendered through the GWC WMS facade.
    """
    if rule is None:
        rule_obj = classify_s57_layer(
            _s57_object_class(layer),
            layer.geometry_type,
            _style_mapped_for_layer(layer),
        )
    else:
        rule_obj = rule  # type: ignore[assignment]

    workspace = layer.geoserver_workspace or settings.geoserver_workspace
    service_url = f"{settings.geoserver_public_url.rstrip('/')}/{workspace}/wms"
    geoserver_layer_name = layer.geoserver_layer_name or layer.code
    loadable = rule_obj.renderable and bool(workspace and geoserver_layer_name)
    cacheable = loadable and rule_obj.load_profile in {"core_chart", "navigation_recommended"}
    render_transport = "gwc_wms" if cacheable else "wms"
    tile_service_url = (
        f"{settings.geoserver_public_url.rstrip('/')}/gwc/service/wms"
        if cacheable
        else service_url
    )
    return cacheable, render_transport, tile_service_url


def _build_resolved_layer(
    link: ProjectLayer,
    layer: Layer,
    object_class: str,
    style_mapped: bool,
    rule: object | None = None,
) -> BulkResolvedLayer:
    """Build a BulkResolvedLayer from a ProjectLayer + Layer with classification."""
    if rule is None:
        rule_obj = classify_s57_layer(object_class, layer.geometry_type, style_mapped)
    else:
        rule_obj = rule  # type: ignore[assignment]

    workspace = layer.geoserver_workspace or settings.geoserver_workspace
    service_url = (
        f"{settings.geoserver_public_url.rstrip('/')}/{workspace}/wms"
    )

    # Determine extent from metadata (EPSG:4326)
    extent = None
    s57_meta = (layer.metadata_json or {}).get("s57")
    if isinstance(s57_meta, dict):
        raw_extent = s57_meta.get("extent")
        if isinstance(raw_extent, list) and len(raw_extent) == 4:
            try:
                extent = [float(v) for v in raw_extent]
            except (ValueError, TypeError):
                pass

    # Determine feature count
    feature_count = None
    if isinstance(s57_meta, dict):
        fc = s57_meta.get("featureCount")
        if isinstance(fc, int):
            feature_count = fc

    # Determine loadability (bare name — truthiness only)
    geoserver_layer_name = layer.geoserver_layer_name or layer.code
    published = bool(workspace and geoserver_layer_name)
    loadable = rule_obj.renderable and published

    skip_reason = None
    if not rule_obj.renderable:
        skip_reason = "non_spatial"
    elif not style_mapped and rule_obj.load_profile in {"core_chart", "navigation_recommended"}:
        skip_reason = "unmapped_style"
    elif not published:
        skip_reason = "unpublished"

    # Phase 4: determine GWC transport and cacheability
    # Core/navigation layers published to GeoServer are likely cacheable via GWC
    cacheable, render_transport, tile_service_url = _gwc_transport_for_layer(layer, rule_obj)

    # Return workspace-qualified names — the GWC WMS facade requires exact
    # "ws:layer" / "ws:style" matches (400 Unknown layer otherwise); GeoServer's
    # own WMS accepts both forms, so qualification is safe for every transport.
    qualified_layer_name = f"{workspace}:{geoserver_layer_name}" if workspace else geoserver_layer_name
    raw_style_name = (
        link.style.geoserver_style_name
        if link.style
        else (layer.metadata_json or {}).get("recommendedStyleCode")
    )
    qualified_style_name = f"{workspace}:{raw_style_name}" if raw_style_name and workspace else raw_style_name

    return BulkResolvedLayer(
        id=layer.id,
        code=layer.code,
        name=layer.name,
        object_class=rule_obj.code,
        object_name_zh=rule_obj.object_name_zh,
        geometry_type=layer.geometry_type,
        geoserver_workspace=workspace,
        geoserver_layer_name=qualified_layer_name,
        service_url=service_url,
        style_name=qualified_style_name,
        opacity=float(link.opacity),
        min_zoom=float(link.min_zoom) if link.min_zoom else None,
        max_zoom=float(link.max_zoom) if link.max_zoom else None,
        extent=extent,
        feature_count=feature_count,
        display_category=rule_obj.display_category,
        load_profile=rule_obj.load_profile,
        display_priority=rule_obj.display_priority,
        recommended=rule_obj.recommended,
        renderable=rule_obj.renderable,
        loadable=loadable,
        style_mapped=style_mapped,
        skip_reason=skip_reason,
        queryable=bool(layer.queryable),
        exportable=bool(layer.exportable),
        group_name=link.group_name,
        sort_order=link.sort_order,
        # Phase 4: GWC transport and scale hints
        render_transport=render_transport,
        tile_service_url=tile_service_url,
        grid_set=None,
        cacheable=cacheable,
        min_scale_denominator=rule_obj.min_scale_denominator,
        max_scale_denominator=rule_obj.max_scale_denominator,
        render_cost=rule_obj.render_cost,
    )


# ── Bulk resolve endpoint ────────────────────────────────────────────


@public_router.post("/{project_id}/map-layers/resolve", response_model=BulkMapLayerResolveResponse)
def resolve_project_map_layers(
    project_id: UUID,
    payload: BulkMapLayerResolveRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BulkMapLayerResolveResponse:
    project = project_or_404(db, project_id, include_unpublished=False)

    # Validate profile
    if payload.profile not in VALID_RESOLVE_PROFILES:
        raise AppError(
            "INVALID_LAYER_PROFILE",
            f"profile 必须为 {', '.join(sorted(VALID_RESOLVE_PROFILES))} 之一",
            422,
        )

    # Validate dataset count
    requested_ids = list(dict.fromkeys(payload.dataset_ids))  # dedup preserving order
    if len(requested_ids) > MAX_RESOLVE_DATASET_IDS:
        raise AppError(
            "BULK_LAYER_DATASET_LIMIT_EXCEEDED",
            f"数据集数量不得超过 {MAX_RESOLVE_DATASET_IDS}",
            422,
        )

    # Fetch all ProjectLayer links with eager-loaded relationships
    links = db.scalars(
        select(ProjectLayer)
        .where(ProjectLayer.project_id == project.id)
        .options(
            selectinload(ProjectLayer.layer)
            .selectinload(Layer.dataset_version)
            .selectinload(DatasetVersion.dataset),
            selectinload(ProjectLayer.style),
        )
        .order_by(ProjectLayer.sort_order)
    ).all()

    # Build lookup: dataset_id → list of (ProjectLayer, Layer)
    dataset_links: dict[UUID, list[tuple[ProjectLayer, Layer]]] = {}
    for link in links:
        layer = link.layer
        if layer.deleted_at is not None:
            continue
        dataset = layer.dataset_version.dataset
        if dataset.current_version_id != layer.dataset_version_id:
            continue
        if dataset.deleted_at is not None:
            continue
        dataset_links.setdefault(dataset.id, []).append((link, layer))

    # Verify all requested dataset IDs belong to the project
    missing = [str(did) for did in requested_ids if did not in dataset_links]
    if missing:
        raise AppError(
            "PROJECT_DATASET_NOT_FOUND",
            f"以下数据集不属于当前项目: {', '.join(missing)}",
            404,
            {"missingDatasetIds": missing},
        )

    profile = payload.profile
    include_metadata = payload.include_metadata

    # Build response datasets
    datasets_result: list[BulkResolvedDataset] = []
    stats = BulkLayerResolveSummary(
        dataset_count=0,
        candidate_count=0,
        loadable_count=0,
        metadata_skipped_count=0,
        non_spatial_skipped_count=0,
        unavailable_skipped_count=0,
        unmapped_style_count=0,
    )

    for dataset_id in requested_ids:
        pair_list = dataset_links[dataset_id]
        if not pair_list:
            continue

        dataset = pair_list[0][1].dataset_version.dataset
        version_no = pair_list[0][1].dataset_version.version_no

        # Only resolve S-57 datasets
        if dataset.data_type != DatasetType.S57.value:
            continue

        resolved_layers: list[BulkResolvedLayer] = []

        for link, layer in pair_list:
            if layer.status != LayerStatus.AVAILABLE.value:
                stats.unavailable_skipped_count += 1
                stats.candidate_count += 1
                continue

            object_class = _s57_object_class(layer)
            style_mapped = _style_mapped_for_layer(layer)
            rule = classify_s57_layer(object_class, layer.geometry_type, style_mapped)
            stats.candidate_count += 1

            # Profile filtering
            is_core = rule.load_profile == "core_chart"
            is_nav = rule.load_profile == "navigation_recommended"
            is_meta = rule.load_profile == "metadata_quality"
            is_non_spatial = rule.load_profile == "non_spatial"

            if is_non_spatial:
                stats.non_spatial_skipped_count += 1
                continue

            if is_meta:
                stats.metadata_skipped_count += 1
                if not include_metadata:
                    continue

            if profile == "core_chart" and not is_core:
                continue
            if profile == "navigation_recommended" and not (is_core or is_nav):
                continue

            if not style_mapped and profile != "all_spatial":
                stats.unmapped_style_count += 1

            resolved_layer = _build_resolved_layer(link, layer, object_class, style_mapped, rule)
            resolved_layers.append(resolved_layer)
            if resolved_layer.loadable:
                stats.loadable_count += 1

        # Stable sort within dataset
        resolved_layers.sort(key=lambda r: (r.display_priority, r.object_class or "", str(r.id)))

        if resolved_layers:
            datasets_result.append(
                BulkResolvedDataset(
                    dataset_id=dataset.id,
                    dataset_code=dataset.code,
                    dataset_name=dataset.name,
                    version_no=version_no,
                    layers=resolved_layers,
                )
            )

    stats.dataset_count = len(datasets_result)

    if not datasets_result:
        raise AppError(
            "NO_LOADABLE_LAYERS",
            "所选数据集中没有可加载的图层",
            404,
            {"summary": stats.model_dump(by_alias=True)},
        )

    return BulkMapLayerResolveResponse(datasets=datasets_result, summary=stats)


# ── Map render plan endpoint ──────────────────────────────────────────


def _compute_data_version_hash(links: list[tuple[ProjectLayer, Layer]]) -> str:
    """Compute a hash over active dataset versions for cache invalidation."""
    import hashlib

    version_fingerprints: list[str] = []
    seen: set[UUID] = set()
    for _link, layer in links:
        dv = layer.dataset_version
        if dv and dv.id not in seen:
            seen.add(dv.id)
            version_fingerprints.append(f"{dv.id}:{dv.version_no}:{dv.content_hash or ''}")
    if not version_fingerprints:
        return ""
    return hashlib.sha256("|".join(sorted(version_fingerprints)).encode()).hexdigest()[:12]


def _build_layer_render_input(link: ProjectLayer, layer: Layer) -> LayerRenderInput | None:
    """Convert a ProjectLayer + Layer to a LayerRenderInput for bundle grouping.

    Returns None for non-spatial layers (should be excluded from bundles).
    """
    object_class = _s57_object_class(layer)
    style_mapped = _style_mapped_for_layer(layer)
    rule = classify_s57_layer(object_class, layer.geometry_type, style_mapped)

    # Non-spatial → excluded from bundles
    if not rule.renderable or rule.load_profile == "non_spatial":
        return None

    workspace = layer.geoserver_workspace or settings.geoserver_workspace
    geoserver_layer_name = (
        f"{workspace}:{layer.geoserver_layer_name or layer.code}"
    )

    style_name = (
        link.style.geoserver_style_name
        if link.style
        else (layer.metadata_json or {}).get("recommendedStyleCode", "")
    )
    if style_name:
        style_name = f"{workspace}:{style_name}"

    # Extract extent from metadata
    extent: tuple[float, ...] | None = None
    s57_meta = (layer.metadata_json or {}).get("s57")
    if isinstance(s57_meta, dict):
        raw_extent = s57_meta.get("extent")
        if isinstance(raw_extent, list) and len(raw_extent) == 4:
            try:
                extent = tuple(float(v) for v in raw_extent)
            except (ValueError, TypeError):
                pass

    return LayerRenderInput(
        layer_id=str(layer.id),
        geoserver_layer_name=geoserver_layer_name,
        style_name=style_name,
        object_class=rule.code,
        display_category=rule.display_category,
        display_priority=rule.display_priority,
        opacity=float(link.opacity),
        extent=extent,
        min_zoom=int(link.min_zoom) if link.min_zoom else None,
        max_zoom=int(link.max_zoom) if link.max_zoom else None,
        render_standalone=False,  # can be set later via metadata
    )


@public_router.post(
    "/{project_id}/map-render/plan",
    response_model=MapRenderPlanResponse,
)
def get_map_render_plan(
    project_id: UUID,
    payload: MapRenderPlanRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> MapRenderPlanResponse:
    """Build a render plan grouping logical layers into composite WMS bundles.

    Only returns layers the user can access in the project.
    Non-spatial layers are excluded. Layers with custom opacity or
    ``renderStandalone`` become standalone layers.
    """
    import hashlib

    project = project_or_404(db, project_id, include_unpublished=False)

    # Fetch all ProjectLayer links with eager-loaded relationships
    links = db.scalars(
        select(ProjectLayer)
        .where(ProjectLayer.project_id == project.id)
        .options(
            selectinload(ProjectLayer.layer)
            .selectinload(Layer.dataset_version)
            .selectinload(DatasetVersion.dataset),
            selectinload(ProjectLayer.style),
        )
        .order_by(ProjectLayer.sort_order)
    ).all()

    # Build layer lookup and filter to only available, current-version layers
    layer_map: dict[UUID, tuple[ProjectLayer, Layer]] = {}
    for link in links:
        layer = link.layer
        if layer.deleted_at is not None:
            continue
        if layer.status != LayerStatus.AVAILABLE.value:
            continue
        dataset = layer.dataset_version.dataset
        if dataset.current_version_id != layer.dataset_version_id:
            continue
        if dataset.deleted_at is not None:
            continue
        layer_map[layer.id] = (link, layer)

    # Validate all requested layer IDs belong to the project
    requested_ids = list(dict.fromkeys(payload.layer_ids))
    missing = [str(lid) for lid in requested_ids if lid not in layer_map]
    if missing:
        raise AppError(
            "PROJECT_LAYER_NOT_FOUND",
            f"以下图层不属于当前项目或不可用: {', '.join(missing)}",
            404,
            {"missingLayerIds": missing},
        )

    # Build LayerRenderInput list
    render_inputs: list[LayerRenderInput] = []
    for lid in requested_ids:
        link, layer = layer_map[lid]
        ri = _build_layer_render_input(link, layer)
        if ri is not None:
            render_inputs.append(ri)

    # Compute data version hash for cache invalidation
    all_valid_links = list(layer_map.values())
    data_version_hash = _compute_data_version_hash(all_valid_links)

    # Build bundles
    bundles, standalones = build_bundles(
        render_inputs,
        payload.profile,
        payload.projection,
        data_version_hash,
    )

    # Compute generation hash (stable fingerprint of the plan)
    generation_raw = "|".join(
        b.cache_key for b in bundles
    ) + "||" + "|".join(
        f"{s.layer_id}:{s.reason}" for s in standalones
    )
    generation = hashlib.sha256(generation_raw.encode()).hexdigest()[:12]

    # Build response
    bundle_outs = [
        BundleConfigOut(
            bundle_id=b.bundle_id,
            bucket=b.bucket,
            layer_ids=[UUID(lid) for lid in b.layer_ids],
            layer_names=b.layer_names,
            styles=b.styles,
            z_index=b.z_index,
            opacity=b.opacity,
            extent=b.extent,
            min_zoom=b.min_zoom,
            max_zoom=b.max_zoom,
            transport=b.transport,
            service_url=b.service_url,
            cache_key=b.cache_key,
        )
        for b in bundles
    ]

    standalone_outs = [
        StandaloneConfigOut(
            layer_id=UUID(s.layer_id),
            layer_name=s.layer_name,
            style=s.style,
            z_index=s.z_index,
            opacity=s.opacity,
            reason=s.reason,
        )
        for s in standalones
    ]

    logical_count = len(bundle_outs) + len(standalone_outs)
    # Sum of bundled layers accounts for layers inside bundles
    total_layers = sum(len(b.layer_ids) for b in bundle_outs) + len(standalone_outs)
    estimated_reduction = (
        1.0 - (logical_count / max(total_layers, 1))
        if total_layers > 0
        else 0.0
    )

    summary = RenderPlanSummaryOut(
        logical_layer_count=total_layers,
        bundle_count=len(bundle_outs),
        standalone_count=len(standalone_outs),
        estimated_request_reduction_ratio=round(estimated_reduction, 3),
    )

    return MapRenderPlanResponse(
        generation=generation,
        bundles=bundle_outs,
        standalone_layers=standalone_outs,
        summary=summary,
    )


@admin_router.get("", response_model=Paginated[ProjectRead])
def list_admin_projects(
    page: int = 1,
    page_size: int = 15,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Paginated[ProjectRead]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    condition = Project.deleted_at.is_(None)
    total = db.scalar(select(func.count()).select_from(Project).where(condition)) or 0
    projects = db.scalars(
        select(Project)
        .where(condition)
        .options(*project_load_options())
        .order_by(Project.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Paginated(
        items=[project_to_read(project) for project in projects],
        page=page,
        page_size=page_size,
        total=total,
    )


@admin_router.post("", response_model=ProjectRead, status_code=201)
def create_project(
    payload: ProjectCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ProjectRead:
    if db.scalar(select(Project).where(Project.code == payload.code, Project.deleted_at.is_(None))):
        raise AppError("PROJECT_CODE_EXISTS", "项目代码已存在", 409)
    project = Project(
        **payload.model_dump(),
        created_by=admin.id,
        updated_by=admin.id,
    )
    db.add(project)
    db.flush()
    write_audit(
        db,
        "project.create",
        "project",
        "succeeded",
        user=admin,
        resource_id=str(project.id),
        request_id=request.state.request_id,
    )
    db.commit()
    db.refresh(project)
    return project_to_read(project)


@admin_router.get("/{project_id}", response_model=ProjectRead)
def get_admin_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ProjectRead:
    return project_to_read(project_or_404(db, project_id))


@admin_router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ProjectRead:
    project = project_or_404(db, project_id)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(project, key, value)
    project.updated_by = admin.id
    write_audit(
        db,
        "project.update",
        "project",
        "succeeded",
        user=admin,
        resource_id=str(project.id),
        request_id=request.state.request_id,
        changes=changes,
    )
    db.commit()
    db.refresh(project)
    return project_to_read(project)


@admin_router.get("/{project_id}/layers", response_model=list[ProjectLayerConfigRead])
def get_project_layers(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[ProjectLayer]:
    project = project_or_404(db, project_id)
    return list(
        db.scalars(
            select(ProjectLayer)
            .where(ProjectLayer.project_id == project.id)
            .order_by(ProjectLayer.sort_order)
        ).all()
    )


@admin_router.put("/{project_id}/layers", response_model=ProjectRead)
def set_project_layers(
    project_id: UUID,
    payload: ProjectLayersUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ProjectRead:
    project = project_or_404(db, project_id)
    layer_ids = [item.layer_id for item in payload.layers]
    if len(layer_ids) != len(set(layer_ids)):
        raise AppError("PROJECT_LAYER_DUPLICATE", "同一图层不能重复配置", 422)
    available_ids = set(
        db.scalars(
            select(Layer.id)
            .join(Dataset, Dataset.current_version_id == Layer.dataset_version_id)
            .where(
                Layer.id.in_(layer_ids),
                Layer.deleted_at.is_(None),
                Dataset.deleted_at.is_(None),
            )
        ).all()
    )
    if available_ids != set(layer_ids):
        raise AppError("LAYER_NOT_FOUND", "一个或多个图层不存在或不是当前有效版本", 404)
    style_ids = {item.style_id for item in payload.layers if item.style_id is not None}
    available_style_ids = set(
        db.scalars(
            select(Style.id).where(
                Style.id.in_(style_ids),
                Style.deleted_at.is_(None),
                Style.status == "published",
            )
        ).all()
    )
    if available_style_ids != style_ids:
        raise AppError("STYLE_NOT_FOUND", "一个或多个样式不存在或尚未发布", 404)
    db.execute(delete(ProjectLayer).where(ProjectLayer.project_id == project.id))
    for item in payload.layers:
        db.add(ProjectLayer(project_id=project.id, **item.model_dump()))
    project.updated_by = admin.id
    write_audit(
        db,
        "project.layers.update",
        "project",
        "succeeded",
        user=admin,
        resource_id=str(project.id),
        request_id=request.state.request_id,
        changes={"layerCount": len(payload.layers)},
    )
    db.commit()
    db.expire(project, ["project_layers"])
    return project_to_read(project_or_404(db, project.id))


@admin_router.get("/{project_id}/dataset-layers", response_model=Paginated[ProjectDatasetLayerRead])
def get_project_dataset_layers(
    project_id: UUID,
    page: int = 1,
    page_size: int = 15,
    search: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Paginated[ProjectDatasetLayerRead]:
    project = project_or_404(db, project_id)
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    available_layer_count = (
        select(func.count(Layer.id))
        .where(
            Layer.dataset_version_id == Dataset.current_version_id,
            Layer.deleted_at.is_(None),
            Layer.status == LayerStatus.AVAILABLE.value,
        )
        .correlate(Dataset)
        .scalar_subquery()
    )
    conditions = [
        Dataset.deleted_at.is_(None),
        Dataset.current_version_id.is_not(None),
        available_layer_count > 0,
    ]
    if search and search.strip():
        keyword = f"%{search.strip()}%"
        conditions.append(
            or_(Dataset.name.ilike(keyword), Dataset.code.ilike(keyword))
        )
    total = db.scalar(select(func.count()).select_from(Dataset).where(*conditions)) or 0
    datasets = db.execute(
        select(Dataset, DatasetVersion, available_layer_count.label("available_layer_count"))
        .join(DatasetVersion, DatasetVersion.id == Dataset.current_version_id)
        .where(*conditions)
        .order_by(Dataset.name, Dataset.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    links = db.scalars(
        select(ProjectLayer)
        .where(ProjectLayer.project_id == project.id)
        .options(
            selectinload(ProjectLayer.layer)
            .selectinload(Layer.dataset_version)
            .selectinload(DatasetVersion.dataset)
        )
        .order_by(ProjectLayer.sort_order)
    ).all()
    selected_by_dataset: dict[UUID, ProjectLayer] = {}
    for link in links:
        if link.layer.deleted_at is None:
            dataset = link.layer.dataset_version.dataset
            if dataset.current_version_id == link.layer.dataset_version_id:
                selected_by_dataset.setdefault(dataset.id, link)

    items = []
    for dataset, version, layer_count in datasets:
        configured = selected_by_dataset.get(dataset.id)
        items.append(
            ProjectDatasetLayerRead(
                dataset_id=dataset.id,
                dataset_code=dataset.code,
                dataset_name=dataset.name,
                data_type=dataset.data_type,
                version_no=version.version_no,
                available_layer_count=layer_count,
                selected=configured is not None,
                group_name=(configured.group_name if configured else ("电子海图" if dataset.data_type == "s57" else "环境数据")),
                sort_order=configured.sort_order if configured else 0,
                visible_by_default=configured.visible_by_default if configured else False,
                opacity=float(configured.opacity) if configured else 1,
            )
        )
    return Paginated(items=items, page=page, page_size=page_size, total=total)


@admin_router.put("/{project_id}/dataset-layers", response_model=ProjectRead)
def set_project_dataset_layers(
    project_id: UUID,
    payload: ProjectDatasetLayersUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ProjectRead:
    project = project_or_404(db, project_id)
    dataset_ids = [item.dataset_id for item in payload.datasets]
    if len(dataset_ids) != len(set(dataset_ids)):
        raise AppError("PROJECT_DATASET_DUPLICATE", "同一数据集不能重复配置", 422)
    datasets = db.scalars(
        select(Dataset).where(
            Dataset.id.in_(dataset_ids),
            Dataset.deleted_at.is_(None),
            Dataset.current_version_id.is_not(None),
        )
    ).all()
    datasets_by_id = {dataset.id: dataset for dataset in datasets}
    if set(dataset_ids) != set(datasets_by_id):
        raise AppError("DATASET_NOT_FOUND", "一个或多个数据集不存在或没有当前有效版本", 404)

    children_by_dataset: dict[UUID, list[Layer]] = {}
    if dataset_ids:
        layers = db.scalars(
            select(Layer)
            .join(Dataset, Dataset.current_version_id == Layer.dataset_version_id)
            .where(
                Dataset.id.in_(dataset_ids),
                Dataset.deleted_at.is_(None),
                Layer.deleted_at.is_(None),
                Layer.status == LayerStatus.AVAILABLE.value,
            )
            .order_by(Dataset.id, Layer.code)
        ).all()
        for layer in layers:
            dataset_id = next(
                dataset.id for dataset in datasets if dataset.current_version_id == layer.dataset_version_id
            )
            children_by_dataset.setdefault(dataset_id, []).append(layer)
    if any(not children_by_dataset.get(dataset_id) for dataset_id in dataset_ids):
        raise AppError("LAYER_NOT_AVAILABLE", "一个或多个数据集没有可用的当前版本图层", 422)

    db.execute(delete(ProjectLayer).where(ProjectLayer.project_id == project.id))
    physical_sort_order = 0
    for item in sorted(payload.datasets, key=lambda value: value.sort_order):
        for layer in children_by_dataset[item.dataset_id]:
            db.add(
                ProjectLayer(
                    project_id=project.id,
                    layer_id=layer.id,
                    style_id=None,
                    group_name=item.group_name,
                    sort_order=physical_sort_order,
                    visible_by_default=item.visible_by_default,
                    opacity=item.opacity,
                )
            )
            physical_sort_order += 1
    project.updated_by = admin.id
    write_audit(
        db,
        "project.dataset_layers.update",
        "project",
        "succeeded",
        user=admin,
        resource_id=str(project.id),
        request_id=request.state.request_id,
        changes={"datasetCount": len(payload.datasets), "physicalLayerCount": physical_sort_order},
    )
    db.commit()
    db.expire(project, ["project_layers"])
    return project_to_read(project_or_404(db, project.id))


@admin_router.post("/{project_id}/publish", response_model=ProjectRead)
def publish_project(
    project_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ProjectRead:
    project = project_or_404(db, project_id)
    configured = db.scalars(
        select(ProjectLayer).where(ProjectLayer.project_id == project.id).options(selectinload(ProjectLayer.layer))
    ).all()
    if not configured or not any(link.layer.status == LayerStatus.AVAILABLE.value for link in configured):
        raise AppError(
            "PROJECT_PUBLISH_VALIDATION_FAILED",
            "项目至少需要一个可用图层",
            422,
        )
    project.status = ProjectStatus.PUBLISHED.value
    project.published_at = datetime.now(UTC)
    project.updated_by = admin.id
    write_audit(
        db,
        "project.publish",
        "project",
        "succeeded",
        user=admin,
        resource_id=str(project.id),
        request_id=request.state.request_id,
    )
    db.commit()
    return project_to_read(project_or_404(db, project.id))


@admin_router.post("/{project_id}/unpublish", response_model=ProjectRead)
def unpublish_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ProjectRead:
    project = project_or_404(db, project_id)
    project.status = ProjectStatus.DRAFT.value
    project.published_at = None
    project.updated_by = admin.id
    db.commit()
    return project_to_read(project_or_404(db, project.id))


@admin_router.post("/{project_id}/archive", response_model=ProjectRead)
def archive_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ProjectRead:
    project = project_or_404(db, project_id)
    project.status = ProjectStatus.ARCHIVED.value
    project.updated_by = admin.id
    db.commit()
    return project_to_read(project_or_404(db, project.id))


@admin_router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> None:
    project = project_or_404(db, project_id)
    project.deleted_at = datetime.now(UTC)
    project.updated_by = admin.id
    db.commit()
