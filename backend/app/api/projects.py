from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_admin
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models import (
    Dataset,
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
    MapConfig,
    MapDatasetConfig,
    MapLayerConfig,
    Paginated,
    ProjectCreate,
    ProjectDatasetLayerRead,
    ProjectDatasetLayersUpdate,
    ProjectLayerConfigRead,
    ProjectLayersUpdate,
    ProjectRead,
    ProjectUpdate,
)
from app.services.audit import write_audit

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
    return [
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
                f"/{link.layer.geoserver_workspace or settings.geoserver_workspace}/wms"
            ),
            service_layer_name=link.layer.geoserver_layer_name or link.layer.code,
            style_name=link.style.geoserver_style_name if link.style else None,
            metadata=link.layer.metadata_json,
        )
        for link in links
    ]


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
