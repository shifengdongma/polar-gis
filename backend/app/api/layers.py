import csv
import io
import json
import re
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models import Dataset, Layer, LayerStatus, User
from app.schemas import (
    ExportRequest,
    FeatureSearchRequest,
    IdentifyRequest,
    LayerRead,
    LayerUpdate,
    Paginated,
)
from app.services.audit import write_audit

public_router = APIRouter(prefix="/layers", tags=["layers"])
admin_router = APIRouter(prefix="/admin/layers", tags=["admin-layers"])
settings = get_settings()
table_pattern = re.compile(r"^geo\.[a-z0-9_]+$")
field_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
operators = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
_NON_SPATIAL_TYPES = frozenset({"unknown", "none", "", "无", "无几何", "geometrycollection"})


def normalize_geo_column_names(db: Session) -> int:
    """Rename uppercase column names in geo.* tables to lowercase.

    Older S-57 imports (pre-LAUNDER=YES) produced uppercase PostgreSQL columns
    (e.g. ``"DSID"``), but ``allowed_fields`` is always stored lowercase.
    Since ``column_reference`` uses unquoted identifiers (PostgreSQL folds to
    lowercase), uppercase column names cause ``column does not exist`` errors.

    This function is idempotent — it only renames columns that contain
    uppercase letters and are not already lowercase.
    """
    renamed = 0
    rows = db.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'geo' AND column_name ~ '[A-Z]'"
        )
    ).fetchall()
    for table_name, column_name in rows:
        lower_name = column_name.lower()
        if lower_name == column_name:
            continue
        try:
            db.execute(
                text(
                    f'ALTER TABLE geo."{table_name}" '
                    f'RENAME COLUMN "{column_name}" TO "{lower_name}"'
                )
            )
            db.commit()
            renamed += 1
        except Exception:
            db.rollback()
    return renamed


def column_reference(field: str) -> str:
    # Unquoted identifier — PostgreSQL folds to lowercase by default.
    # This matches the LAUNDER=YES lowercase column names produced by ogr2ogr.
    # The field is already validated by field_pattern to contain only safe chars.
    return field


def selected_column(field: str) -> str:
    return f'{column_reference(field)} AS "{field}"'


def layer_or_404(db: Session, layer_id: UUID, available_only: bool = False) -> Layer:
    conditions = [Layer.id == layer_id, Layer.deleted_at.is_(None)]
    if available_only:
        conditions.append(Layer.status == LayerStatus.AVAILABLE.value)
    layer = db.scalar(select(Layer).where(*conditions))
    if layer is None:
        raise AppError("LAYER_NOT_AVAILABLE", "图层不存在或不可用", 404)
    return layer


def safe_source_table(layer: Layer) -> str:
    if not layer.source_table or not table_pattern.fullmatch(layer.source_table):
        raise AppError("LAYER_SOURCE_INVALID", "图层数据源配置无效", 500)
    return layer.source_table


def _layer_has_geometry(layer: Layer) -> bool:
    """Return True if the layer has a usable geometry column."""
    geom_type = (layer.geometry_type or "").strip().lower()
    return geom_type not in _NON_SPATIAL_TYPES


def allowed_fields(layer: Layer, requested: list[str] | None = None) -> list[str]:
    configured = [field for field in layer.allowed_fields if field_pattern.fullmatch(field)]
    if not requested:
        return configured
    if not set(requested).issubset(configured):
        raise AppError("QUERY_FIELD_NOT_ALLOWED", "查询包含不允许的字段", 422)
    return requested


def build_where(layer: Layer, payload: FeatureSearchRequest | ExportRequest) -> tuple[str, dict[str, Any]]:
    clauses = []
    params: dict[str, Any] = {}
    configured = set(allowed_fields(layer))
    for index, item in enumerate(payload.filters):
        if item.field not in configured or not field_pattern.fullmatch(item.field):
            raise AppError("QUERY_FIELD_NOT_ALLOWED", f"字段{item.field}不允许查询", 422)
        parameter = f"value_{index}"
        if item.operator in operators:
            clauses.append(f'{column_reference(item.field)} {operators[item.operator]} :{parameter}')
            params[parameter] = item.value
        elif item.operator == "contains":
            clauses.append(f'CAST({column_reference(item.field)} AS TEXT) ILIKE :{parameter}')
            params[parameter] = f"%{item.value}%"
        elif item.operator == "in" and isinstance(item.value, list):
            names = []
            for value_index, value in enumerate(item.value):
                name = f"{parameter}_{value_index}"
                names.append(f":{name}")
                params[name] = value
            clauses.append(f'{column_reference(item.field)} IN ({", ".join(names)})')
        else:
            raise AppError("QUERY_OPERATOR_NOT_ALLOWED", "查询操作符不允许", 422)
    if payload.bbox:
        clauses.append("geom && ST_Transform(ST_MakeEnvelope(:xmin,:ymin,:xmax,:ymax,4326), ST_SRID(geom))")
        params.update(
            xmin=payload.bbox[0],
            ymin=payload.bbox[1],
            xmax=payload.bbox[2],
            ymax=payload.bbox[3],
        )
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


@admin_router.get("", response_model=Paginated[LayerRead])
def list_layers(
    page: int = 1,
    page_size: int = 15,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Paginated[LayerRead]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    conditions = [
        Layer.deleted_at.is_(None),
        Dataset.deleted_at.is_(None),
        Dataset.current_version_id == Layer.dataset_version_id,
    ]
    base_query = select(Layer).join(
        Dataset, Dataset.current_version_id == Layer.dataset_version_id
    )
    total = db.scalar(
        select(func.count()).select_from(Layer).join(
            Dataset, Dataset.current_version_id == Layer.dataset_version_id
        ).where(*conditions)
    ) or 0
    layers = db.scalars(
        base_query
        .where(*conditions)
        .order_by(Layer.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Paginated(items=list(layers), page=page, page_size=page_size, total=total)


@admin_router.patch("/{layer_id}", response_model=LayerRead)
def update_layer(
    layer_id: UUID,
    payload: LayerUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Layer:
    layer = layer_or_404(db, layer_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(layer, key, value)
    db.commit()
    db.refresh(layer)
    return layer


@admin_router.post("/{layer_id}/disable", response_model=LayerRead)
def disable_layer(
    layer_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Layer:
    layer = layer_or_404(db, layer_id)
    layer.status = LayerStatus.DISABLED.value
    db.commit()
    db.refresh(layer)
    return layer


@public_router.get("/{layer_id}/metadata", response_model=LayerRead)
def layer_metadata(
    layer_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Layer:
    return layer_or_404(db, layer_id, available_only=True)


@public_router.get("/{layer_id}/legend")
def layer_legend(
    layer_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, str]:
    layer = layer_or_404(db, layer_id, available_only=True)
    workspace = layer.geoserver_workspace or settings.geoserver_workspace
    layer_name = layer.geoserver_layer_name or layer.code
    query = urlencode(
        {
            "service": "WMS",
            "request": "GetLegendGraphic",
            "format": "image/png",
            "transparent": "true",
            "layer": f"{workspace}:{layer_name}",
        }
    )
    return {"url": f"{settings.geoserver_public_url.rstrip('/')}/{workspace}/wms?{query}"}


@public_router.post("/{layer_id}/identify")
def identify_feature(
    layer_id: UUID,
    payload: IdentifyRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    layer = layer_or_404(db, layer_id, available_only=True)
    if not layer.queryable:
        raise AppError("LAYER_QUERY_DISABLED", "当前图层不允许查询", 403)
    if not _layer_has_geometry(layer):
        raise AppError("LAYER_NON_SPATIAL", "非空间图层不支持要素识别", 400)
    table = safe_source_table(layer)
    fields = allowed_fields(layer)
    selected = ", ".join(selected_column(field) for field in fields)
    prefix = f"{selected}, " if selected else ""
    sql = text(
        f"SELECT {prefix}ST_AsGeoJSON(ST_Transform(geom,4326)) AS geometry "
        f"FROM {table} WHERE ST_DWithin(geom, ST_Transform(ST_SetSRID(ST_Point(:x,:y),4326), ST_SRID(geom)), :distance) LIMIT 10"
    )
    rows = db.execute(
        sql,
        {"x": payload.coordinate[0], "y": payload.coordinate[1], "distance": payload.tolerance},
    ).mappings()
    return {"items": [dict(row) for row in rows], "layerId": str(layer.id)}


@public_router.post("/{layer_id}/features/search")
def search_features(
    layer_id: UUID,
    payload: FeatureSearchRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    layer = layer_or_404(db, layer_id, available_only=True)
    if not layer.queryable:
        raise AppError("LAYER_QUERY_DISABLED", "当前图层不允许查询", 403)
    table = safe_source_table(layer)
    fields = allowed_fields(layer)
    where_sql, params = build_where(layer, payload)
    total = db.scalar(text(f"SELECT COUNT(*) FROM {table}{where_sql}"), params) or 0
    field_sql = ", ".join(selected_column(field) for field in fields)
    prefix = f"{field_sql}, " if field_sql else ""
    geom_expr = "ST_AsGeoJSON(ST_Transform(geom,4326)) AS geometry" if _layer_has_geometry(layer) else "NULL AS geometry"
    params.update(limit=payload.page_size, offset=(payload.page - 1) * payload.page_size)
    rows = db.execute(
        text(
            f"SELECT {prefix}{geom_expr} "
            f"FROM {table}{where_sql} LIMIT :limit OFFSET :offset"
        ),
        params,
    ).mappings()
    return {
        "items": [dict(row) for row in rows],
        "page": payload.page,
        "pageSize": payload.page_size,
        "total": total,
    }


@public_router.post("/{layer_id}/exports")
def export_features(
    layer_id: UUID,
    payload: ExportRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    layer = layer_or_404(db, layer_id, available_only=True)
    if not layer.exportable:
        raise AppError("LAYER_EXPORT_DISABLED", "当前图层不允许导出", 403)
    table = safe_source_table(layer)
    fields = allowed_fields(layer, payload.fields)
    where_sql, params = build_where(layer, payload)
    field_sql = ", ".join(selected_column(field) for field in fields)
    prefix = f"{field_sql}, " if field_sql else ""
    geom_expr = "ST_AsGeoJSON(ST_Transform(geom,4326)) AS geometry" if _layer_has_geometry(layer) else "NULL AS geometry"
    params["limit"] = settings.query_result_limit + 1
    rows = list(
        db.execute(
            text(
                f"SELECT {prefix}{geom_expr} "
                f"FROM {table}{where_sql} LIMIT :limit"
            ),
            params,
        ).mappings()
    )
    if len(rows) > settings.query_result_limit:
        raise AppError("EXPORT_LIMIT_EXCEEDED", "导出结果超过允许数量", 422)
    write_audit(
        db,
        "layer.export",
        "layer",
        "succeeded",
        user=user,
        resource_id=str(layer.id),
        request_id=request.state.request_id,
        changes={"format": payload.format, "count": len(rows)},
    )
    db.commit()
    if payload.format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[*fields, "geometry"])
        writer.writeheader()
        writer.writerows(dict(row) for row in rows)
        return Response(
            output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{layer.code}.csv"'},
        )
    features = [
        {
            "type": "Feature",
            "geometry": json.loads(row["geometry"]) if row["geometry"] else None,
            "properties": {field: row[field] for field in fields},
        }
        for row in rows
    ]
    return Response(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        media_type="application/geo+json",
        headers={"Content-Disposition": f'attachment; filename="{layer.code}.geojson"'},
    )
