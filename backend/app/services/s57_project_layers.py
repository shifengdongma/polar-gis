"""Generic project-scoped S-57 layer resolution.

Unlike :mod:`app.services.s57_waterways`, this resolver does not restrict the
result to the waterway taxonomy. It is the shared read-only inventory used by
the waterway diagnostics endpoint and by the thematic depth/hazard export.

The resolver only exposes project-associated layers whose dataset is on its
current version. It never re-opens ``.000`` files and never accepts table or
column names from a client.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models import (
    Dataset,
    DatasetType,
    DatasetVersion,
    Layer,
    LayerStatus,
    ProjectLayer,
)
from app.services.s57_layer_catalog import has_valid_geometry
from app.services.s57_waterways import (
    _COLUMN_PATTERN,
    _TABLE_PATTERN,
    _s57_metadata,
    _source_cell,
    load_table_metadata,
    object_class_for_layer,
)


@dataclass(frozen=True)
class ProjectS57LayerRef:
    layer_id: UUID
    layer_code: str
    layer_name: str
    dataset_id: UUID
    dataset_code: str
    dataset_name: str
    version_no: int
    source_cell: str | None
    object_class: str
    source_table: str | None
    geometry_type: str | None
    fields: tuple[str, ...]
    key_column: str | None
    key_type: str | None
    geometry_column: str | None
    feature_count: int | None
    available: bool
    queryable: bool
    renderable: bool
    reason: str | None
    updated_at: datetime | None
    version_id: UUID | None = None
    content_hash: str | None = None
    extent: tuple[float, float, float, float] | None = None

    @property
    def searchable(self) -> bool:
        return (
            self.available
            and self.queryable
            and bool(self.source_table)
            and bool(self.key_column)
            and bool(self.fields or self.geometry_column)
        )

    def matches_source_cells(self, requested: set[str]) -> bool:
        if not requested:
            return True
        return bool(self.source_cell) and self.source_cell.strip().upper() in requested


@dataclass(frozen=True)
class ProjectS57Resolution:
    layers: tuple[ProjectS57LayerRef, ...]
    warnings: tuple[str, ...] = ()
    candidate_layer_count: int = 0
    resolved_layer_count: int = 0


def _parse_extent(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        xmin, ymin, xmax, ymax = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in (xmin, ymin, xmax, ymax)):
        return None
    # S-57 extents are WGS84 lon/lat. Do not trust projected/garbage extents.
    if not (-180.0 <= xmin <= 180.0 and -180.0 <= xmax <= 180.0):
        return None
    if not (-90.0 <= ymin < ymax <= 90.0):
        return None
    return (xmin, ymin, xmax, ymax)


def resolve_project_s57_layers(
    db: Session, project_id: UUID
) -> ProjectS57Resolution:
    """Resolve every current-version S-57 layer associated with a project."""
    settings = get_settings()
    links = db.scalars(
        select(ProjectLayer)
        .join(Layer, ProjectLayer.layer_id == Layer.id)
        .join(DatasetVersion, Layer.dataset_version_id == DatasetVersion.id)
        .join(Dataset, DatasetVersion.dataset_id == Dataset.id)
        .where(
            ProjectLayer.project_id == project_id,
            Dataset.data_type == DatasetType.S57.value,
            Dataset.current_version_id == Layer.dataset_version_id,
            Dataset.deleted_at.is_(None),
            Layer.deleted_at.is_(None),
        )
        .options(
            selectinload(ProjectLayer.layer)
            .selectinload(Layer.dataset_version)
            .selectinload(DatasetVersion.dataset)
        )
        .order_by(ProjectLayer.sort_order, Layer.code)
    ).all()

    candidates: list[tuple[ProjectLayer, Layer, str]] = []
    for link in links:
        layer = link.layer
        if layer is None:
            continue
        candidates.append((link, layer, object_class_for_layer(layer)))

    tables = [
        layer.source_table
        for _, layer, _ in candidates
        if layer.source_table and _TABLE_PATTERN.fullmatch(layer.source_table)
    ]
    batch_size = max(1, settings.s57_waterway_introspection_batch_size)
    metadata: dict[str, Any] = {}
    for start in range(0, len(tables), batch_size):
        metadata.update(load_table_metadata(db, tables[start : start + batch_size]))

    warnings: list[str] = []
    if len(candidates) > settings.s57_waterway_query_warning_layers:
        warnings.append(
            f"项目 S-57 图层较多（{len(candidates)} 个），诊断或专题提取可能较慢"
        )

    layers: list[ProjectS57LayerRef] = []
    for _link, layer, code in candidates:
        version = layer.dataset_version
        dataset = version.dataset if version is not None else None
        if version is None or dataset is None:
            continue
        table_meta = metadata.get(layer.source_table or "")
        available = layer.status == LayerStatus.AVAILABLE.value
        queryable = bool(layer.queryable)
        geometry_type = layer.geometry_type
        renderable = available and has_valid_geometry(geometry_type) and bool(
            table_meta and table_meta.geometry_column
        )
        reason: str | None = None
        if not available:
            reason = "图层未启用或发布失败"
        elif not queryable:
            reason = "图层不允许查询"
        elif table_meta is None:
            reason = "要素表不存在或不可访问"
        elif table_meta.key_column is None:
            reason = "缺少稳定的源要素标识"
        elif not has_valid_geometry(geometry_type):
            reason = "非空间对象，仅可查询属性"

        fields: tuple[str, ...] = ()
        if table_meta is not None:
            configured = [
                str(field).lower()
                for field in (layer.allowed_fields or [])
                if _COLUMN_PATTERN.fullmatch(str(field).lower())
                and str(field).lower() in table_meta.columns
                and str(field).lower() != table_meta.key_column
            ]
            if not configured:
                configured = [
                    column
                    for column in table_meta.columns
                    if column != table_meta.geometry_column
                    and column != table_meta.key_column
                ]
            fields = tuple(dict.fromkeys(configured))

        s57 = _s57_metadata(layer)
        raw_count = s57.get("featureCount")
        feature_count: int | None
        try:
            feature_count = int(raw_count) if raw_count is not None else None
        except (TypeError, ValueError):
            feature_count = None
        # Do not auto-COUNT every project layer here: a large ENC library can
        # contain thousands of tables, and COUNT(*) holds AccessShareLocks
        # until transaction end (PostgreSQL max_locks_per_transaction). The
        # catalog/diagnostics mark missing metadata counts as "unknown" rather
        # than risking a poisoned/lock-exhausted session.


        layers.append(
            ProjectS57LayerRef(
                layer_id=layer.id,
                layer_code=layer.code,
                layer_name=layer.name,
                dataset_id=dataset.id,
                dataset_code=dataset.code,
                dataset_name=dataset.name,
                version_no=version.version_no,
                source_cell=_source_cell(dataset, version),
                object_class=code,
                source_table=layer.source_table,
                geometry_type=geometry_type,
                fields=fields,
                key_column=table_meta.key_column if table_meta else None,
                key_type=table_meta.key_type if table_meta else None,
                geometry_column=table_meta.geometry_column if table_meta else None,
                feature_count=feature_count,
                available=available,
                queryable=queryable,
                renderable=renderable,
                reason=reason,
                updated_at=version.activated_at or version.created_at,
                version_id=version.id,
                content_hash=version.content_hash,
                extent=_parse_extent(s57.get("extent")),
            )
        )

    return ProjectS57Resolution(
        layers=tuple(layers),
        warnings=tuple(warnings),
        candidate_layer_count=len(candidates),
        resolved_layer_count=len(layers),
    )
