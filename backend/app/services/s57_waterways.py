"""Project-scoped S-57 waterway thematic queries.

Reads the already imported ``geo.*`` feature tables through Layer metadata. It
never re-opens ``.000`` files, never accepts table/schema/column names from the
client, and enforces project + current dataset version + available/queryable
layer constraints.

The cross-layer search is a federated ``UNION ALL`` over the selected layers'
tables. Identifiers come only from the database and are validated/quoted; all
values (keyword, bbox, page, feature key) are bound parameters.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import (
    Dataset,
    DatasetType,
    DatasetVersion,
    Layer,
    LayerStatus,
    ProjectLayer,
)
from app.services.s57_layer_catalog import has_valid_geometry
from app.services.s57_waterway_catalog import (
    CURATED_FIELD_ORDER,
    FIELD_DESCRIPTIONS,
    S57_WATERWAY_ALL_CLASSES,
    WaterwayClassRule,
    classify_waterway,
    field_label,
    normalize_object_class,
)

logger = logging.getLogger(__name__)

_TABLE_PATTERN = re.compile(r"^geo\.[a-z0-9_]+$")
_COLUMN_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")
_NAME_FIELDS = ("objnam", "nobjnm")
_INFORM_FIELDS = ("inform", "ninfom")
_KEY_CANDIDATES = ("ogc_fid", "fid", "rcid", "lnam")
_NUMERIC_TYPES = frozenset(
    {"smallint", "integer", "bigint", "numeric", "real", "double precision", "serial", "bigserial"}
)


@dataclass(frozen=True)
class TableMeta:
    columns: frozenset[str]
    key_column: str | None
    key_type: str | None
    geometry_column: str | None
    srid: int | None


@dataclass(frozen=True)
class WaterwayLayerRef:
    layer_id: UUID
    layer_code: str
    layer_name: str
    dataset_id: UUID
    dataset_code: str
    dataset_name: str
    version_no: int
    source_cell: str | None
    object_class: str
    rule: WaterwayClassRule
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

    @property
    def searchable(self) -> bool:
        return (
            self.available
            and self.queryable
            and bool(self.source_table)
            and bool(self.key_column)
            and bool(self.fields or self.geometry_column)
        )


@dataclass(frozen=True)
class WaterwayResolution:
    layers: tuple[WaterwayLayerRef, ...]
    warnings: tuple[str, ...]
    truncated: bool = False


def _s57_metadata(layer: Layer) -> dict[str, Any]:
    metadata = layer.metadata_json or {}
    value = metadata.get("s57")
    return value if isinstance(value, dict) else {}


def object_class_for_layer(layer: Layer) -> str:
    metadata = layer.metadata_json or {}
    s57 = _s57_metadata(layer)
    raw = s57.get("objectClass") or metadata.get("objectClass") or metadata.get("sourceLayer") or layer.name
    return normalize_object_class(str(raw) if raw else "")


def _source_cell(dataset: Dataset, version: DatasetVersion) -> str | None:
    cell = (version.metadata_json or {}).get("cellName")
    if cell:
        return str(cell)
    if dataset.name:
        return dataset.name.removeprefix("S-57 海图 ").strip() or dataset.name
    return dataset.code or None


def _quote_identifier(name: str) -> str:
    if not _COLUMN_PATTERN.fullmatch(name):
        raise AppError("S57_WATERWAY_SOURCE_INVALID", "图层字段名无效", 500)
    return f'"{name}"'


def _safe_table(source_table: str | None) -> str:
    if not source_table or not _TABLE_PATTERN.fullmatch(source_table):
        raise AppError("S57_WATERWAY_SOURCE_INVALID", "图层数据源配置无效", 500)
    return source_table


def _table_parts(source_table: str) -> tuple[str, str]:
    schema, table = source_table.split(".", maxsplit=1)
    return schema, table


def _key_type(data_type: str | None) -> str:
    normalized = (data_type or "").lower()
    return "int" if normalized in _NUMERIC_TYPES else "text"


def load_table_metadata(db: Session, source_tables: list[str]) -> dict[str, TableMeta]:
    """Batch-introspect actual columns and primary keys for the given tables."""
    if not source_tables:
        return {}
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        table_names = [_table_parts(item)[1] for item in source_tables]
        columns_stmt = (
            text(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'geo' AND table_name IN :names"
            ).bindparams(bindparam("names", expanding=True))
        )
        column_rows = db.execute(columns_stmt, {"names": table_names}).all()
        pk_stmt = (
            text(
                "SELECT tc.table_name, kcu.column_name "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "  ON tc.constraint_name = kcu.constraint_name "
                " AND tc.table_schema = kcu.table_schema "
                "WHERE tc.table_schema = 'geo' AND tc.constraint_type = 'PRIMARY KEY' "
                "  AND tc.table_name IN :names"
            ).bindparams(bindparam("names", expanding=True))
        )
        pk_rows = db.execute(pk_stmt, {"names": table_names}).all()
        primary_keys: dict[str, list[str]] = {}
        for table_name, column_name in pk_rows:
            primary_keys.setdefault(str(table_name), []).append(str(column_name).lower())
        column_map: dict[str, dict[str, str]] = {}
        for table_name, column_name, data_type in column_rows:
            column_map.setdefault(str(table_name), {})[str(column_name).lower()] = str(data_type)
        srid_map: dict[str, int] = {}
        try:
            srid_rows = db.execute(
                text(
                    "SELECT f_table_name, srid FROM geometry_columns "
                    "WHERE f_table_schema = 'geo' AND f_geometry_column = 'geom' "
                    "  AND f_table_name IN :names"
                ).bindparams(bindparam("names", expanding=True)),
                {"names": table_names},
            ).all()
            srid_map = {str(table_name): int(srid) for table_name, srid in srid_rows}
        except DBAPIError:
            srid_map = {}
    else:
        # SQLite unit tests: SQLAlchemy inspector is sufficient for plain
        # columns. PostGIS-only SQL is exercised by the optional integration
        # test with a real PostgreSQL database.
        engine = db.get_bind()
        inspector = inspect(engine)
        column_map = {}
        primary_keys = {}
        srid_map = {}
        for source_table in source_tables:
            _, table_name = _table_parts(source_table)
            try:
                columns = inspector.get_columns(table_name, schema="geo")
                pk = inspector.get_pk_constraint(table_name, schema="geo") or {}
            except Exception:  # noqa: BLE001 - unavailable table -> catalog reason
                continue
            column_map[table_name] = {
                str(column["name"]).lower(): str(column.get("type", "")) for column in columns
            }
            primary_keys[table_name] = [
                str(name).lower() for name in (pk.get("constrained_columns") or [])
            ]

    result: dict[str, TableMeta] = {}
    for source_table in source_tables:
        _, table_name = _table_parts(source_table)
        columns = column_map.get(table_name)
        if not columns:
            continue
        key_column = None
        for candidate in [*(primary_keys.get(table_name) or []), *_KEY_CANDIDATES]:
            if candidate in columns:
                key_column = candidate
                break
        geometry_column = "geom" if "geom" in columns else None
        srid = srid_map.get(table_name)
        result[source_table] = TableMeta(
            columns=frozenset(columns),
            key_column=key_column,
            key_type=_key_type(columns.get(key_column)) if key_column else None,
            geometry_column=geometry_column,
            srid=srid,
        )
    return result


def resolve_waterway_layers(db: Session, project_id: UUID) -> WaterwayResolution:
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
        code = object_class_for_layer(layer)
        if code not in S57_WATERWAY_ALL_CLASSES:
            continue
        candidates.append((link, layer, code))

    truncated = len(candidates) > settings.s57_waterway_max_layers
    if truncated:
        candidates = candidates[: settings.s57_waterway_max_layers]

    tables = [
        layer.source_table
        for _, layer, _ in candidates
        if layer.source_table and _TABLE_PATTERN.fullmatch(layer.source_table)
    ]
    metadata = load_table_metadata(db, tables)
    warnings: list[str] = []
    if truncated:
        warnings.append(
            f"项目航道图层超过 {settings.s57_waterway_max_layers} 个，仅展示前 "
            f"{settings.s57_waterway_max_layers} 个图层"
        )

    layers: list[WaterwayLayerRef] = []
    for _link, layer, code in candidates:
        rule = classify_waterway(code)
        if rule is None:
            continue
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
        if feature_count is None and available and table_meta is not None:
            try:
                feature_count = int(
                    db.scalar(text(f"SELECT COUNT(*) FROM {_safe_table(layer.source_table)}")) or 0
                )
            except DBAPIError:
                feature_count = None

        updated_at = version.activated_at or version.created_at
        layers.append(
            WaterwayLayerRef(
                layer_id=layer.id,
                layer_code=layer.code,
                layer_name=layer.name,
                dataset_id=dataset.id,
                dataset_code=dataset.code,
                dataset_name=dataset.name,
                version_no=version.version_no,
                source_cell=_source_cell(dataset, version),
                object_class=code,
                rule=rule,
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
                updated_at=updated_at,
            )
        )
    return WaterwayResolution(layers=tuple(layers), warnings=tuple(warnings), truncated=truncated)


def _layer_ref(layer: WaterwayLayerRef) -> dict[str, Any]:
    return {
        "id": str(layer.layer_id),
        "name": layer.layer_name,
        "code": layer.layer_code,
        "datasetCode": layer.dataset_code,
        "datasetName": layer.dataset_name,
        "versionNo": layer.version_no,
        "sourceCell": layer.source_cell,
        "featureCount": layer.feature_count,
        "queryable": layer.queryable,
        "renderable": layer.renderable,
        "available": layer.available and layer.searchable,
        "reason": layer.reason,
    }


def build_catalog(resolution: WaterwayResolution) -> dict[str, Any]:
    by_class: dict[str, list[WaterwayLayerRef]] = {}
    for layer in resolution.layers:
        by_class.setdefault(layer.object_class, []).append(layer)

    classes: list[dict[str, Any]] = []
    warnings = list(resolution.warnings)
    # Ensure all primary classes are represented even when count is zero.
    from app.services.s57_waterway_catalog import WATERWAY_CLASS_RULES

    codes = [code for code in WATERWAY_CLASS_RULES if not WATERWAY_CLASS_RULES[code].auxiliary]
    codes.extend(
        code
        for code in WATERWAY_CLASS_RULES
        if WATERWAY_CLASS_RULES[code].auxiliary and code in by_class
    )
    total = 0
    count_complete = True
    for code in codes:
        rule = WATERWAY_CLASS_RULES[code]
        layers = by_class.get(code, [])
        counts = [layer.feature_count for layer in layers]
        if any(count is None for count in counts):
            count_complete = False
        class_count = sum(count for count in counts if count is not None)
        total += class_count
        classes.append(
            {
                "code": rule.code,
                "nameZh": rule.name_zh,
                "group": rule.group,
                "groupNameZh": rule.group_name_zh,
                "auxiliary": rule.auxiliary,
                "defaultSelected": rule.default_selected,
                "description": rule.description,
                "count": class_count,
                "layerCount": len(layers),
                "queryable": any(layer.searchable for layer in layers),
                "renderable": any(layer.renderable for layer in layers),
                "layers": [_layer_ref(layer) for layer in layers],
            }
        )
    return {
        "classes": classes,
        "total": total,
        "countComplete": count_complete,
        "truncated": resolution.truncated,
        "warnings": warnings,
    }


def _selected_codes(payload: Any) -> tuple[set[str], list[str]]:
    requested = [normalize_object_class(code) for code in (payload.object_classes or [])]
    warnings: list[str] = []
    if requested:
        unknown = [code for code in requested if code not in S57_WATERWAY_ALL_CLASSES]
        if unknown:
            raise AppError(
                "S57_WATERWAY_OBJECT_CLASS_INVALID",
                f"不支持的航道对象类别：{', '.join(unknown)}",
                422,
            )
        auxiliary = [
            code
            for code in requested
            if classify_waterway(code) is not None and classify_waterway(code).auxiliary
        ]
        if auxiliary and not payload.include_auxiliary:
            raise AppError(
                "S57_WATERWAY_AUXILIARY_DISABLED",
                "辅助要素需显式开启 includeAuxiliary 后才能查询",
                422,
            )
        return set(requested), warnings
    from app.services.s57_waterway_catalog import WATERWAY_CLASS_RULES

    selected = {
        code
        for code, rule in WATERWAY_CLASS_RULES.items()
        if not rule.auxiliary and rule.default_selected
    }
    if payload.include_auxiliary:
        selected |= {
            code for code, rule in WATERWAY_CLASS_RULES.items() if rule.auxiliary
        }
    return selected, warnings


def _name_expr(layer: WaterwayLayerRef) -> str:
    fields = set(layer.fields)
    present = [field for field in _NAME_FIELDS if field in fields]
    if not present:
        return "NULL::text"
    parts = [
        f"NULLIF(BTRIM(CAST(w.{_quote_identifier(field)} AS TEXT)), '')" for field in present
    ]
    return f"COALESCE({', '.join(parts)})"


def _name_field_expr(layer: WaterwayLayerRef) -> str:
    fields = set(layer.fields)
    present = [field for field in _NAME_FIELDS if field in fields]
    if not present:
        return "NULL::text"
    cases = [
        f"WHEN NULLIF(BTRIM(CAST(w.{_quote_identifier(field)} AS TEXT)), '') IS NOT NULL "
        f"THEN '{field.upper()}'"
        for field in present
    ]
    return f"CASE {' '.join(cases)} ELSE NULL END"


def _inform_expr(layer: WaterwayLayerRef) -> str:
    fields = set(layer.fields)
    present = [field for field in _INFORM_FIELDS if field in fields]
    if not present:
        return "NULL::text"
    parts = [
        f"NULLIF(BTRIM(CAST(w.{_quote_identifier(field)} AS TEXT)), '')" for field in present
    ]
    return f"COALESCE({', '.join(parts)})"


def _bbox_condition(
    layer: WaterwayLayerRef,
    bbox: tuple[float, float, float, float],
    params: dict[str, Any],
    index: int,
) -> str:
    if not layer.geometry_column:
        return ""
    xmin, ymin, xmax, ymax = bbox
    envelope = (
        "ST_Transform(ST_MakeEnvelope(:{xmin}, :{ymin}, :{xmax}, :{ymax}, 4326), "
        f"ST_SRID(w.{_quote_identifier(layer.geometry_column)}))"
    )
    if xmin <= xmax:
        names = {
            "xmin": f"bbox_{index}_xmin",
            "ymin": f"bbox_{index}_ymin",
            "xmax": f"bbox_{index}_xmax",
            "ymax": f"bbox_{index}_ymax",
        }
        params.update(
            {
                names["xmin"]: xmin,
                names["ymin"]: ymin,
                names["xmax"]: xmax,
                names["ymax"]: ymax,
            }
        )
        return (
            f"w.{_quote_identifier(layer.geometry_column)} && "
            + envelope.format(**names)
        )
    # Antimeridian crossing: split into two envelopes.
    names_a = {
        "xmin": f"bbox_{index}_axmin",
        "ymin": f"bbox_{index}_aymin",
        "xmax": f"bbox_{index}_axmax",
        "ymax": f"bbox_{index}_aymax",
    }
    names_b = {
        "xmin": f"bbox_{index}_bxmin",
        "ymin": f"bbox_{index}_bymin",
        "xmax": f"bbox_{index}_bxmax",
        "ymax": f"bbox_{index}_bymax",
    }
    params.update(
        {
            names_a["xmin"]: -180.0,
            names_a["ymin"]: ymin,
            names_a["xmax"]: xmax,
            names_a["ymax"]: ymax,
            names_b["xmin"]: xmin,
            names_b["ymin"]: ymin,
            names_b["xmax"]: 180.0,
            names_b["ymax"]: ymax,
        }
    )
    geom = f"w.{_quote_identifier(layer.geometry_column)}"
    return (
        f"({geom} && {envelope.format(**names_a)} OR "
        f"{geom} && {envelope.format(**names_b)})"
    )


def _keyword_condition(layer: WaterwayLayerRef, keyword: str, index: int, params: dict[str, Any]) -> str:
    fields = set(layer.fields)
    searchable = [field for field in (*_NAME_FIELDS, *_INFORM_FIELDS) if field in fields]
    if not searchable:
        return ""
    param = f"keyword_{index}"
    params[param] = keyword
    parts = [
        f"strpos(lower(CAST(w.{_quote_identifier(field)} AS TEXT)), lower(:{param})) > 0"
        for field in searchable
    ]
    return f"({' OR '.join(parts)})"


def build_waterway_search_sql(
    layers: list[WaterwayLayerRef],
    payload: Any,
) -> tuple[str, str, dict[str, Any]]:
    """Return (count_sql, rows_sql, params). Pure/unit-testable."""
    params: dict[str, Any] = {}
    selects: list[str] = []
    keyword = (payload.keyword or "").strip()
    bbox = payload.bbox
    usable: list[WaterwayLayerRef] = []
    for layer in layers:
        if not layer.searchable:
            continue
        if bbox and not layer.geometry_column:
            continue
        if keyword and not any(field in layer.fields for field in (*_NAME_FIELDS, *_INFORM_FIELDS)):
            continue
        usable.append(layer)
    for index, layer in enumerate(usable):
        table = _safe_table(layer.source_table)
        if not layer.key_column:
            continue
        key = _quote_identifier(layer.key_column)
        geometry = (
            f"ST_AsGeoJSON(ST_Transform(w.{_quote_identifier(layer.geometry_column)}, 4326))"
            if layer.geometry_column
            else "NULL::text"
        )
        status = (
            f"CAST(w.{_quote_identifier('status')} AS TEXT)"
            if "status" in layer.fields
            else "NULL::text"
        )
        layer_param = f"layer_id_{index}"
        order_param = f"layer_order_{index}"
        class_param = f"object_class_{index}"
        params[layer_param] = str(layer.layer_id)
        params[order_param] = index
        params[class_param] = layer.object_class
        conditions: list[str] = []
        keyword_condition = _keyword_condition(layer, keyword, index, params) if keyword else ""
        if keyword_condition:
            conditions.append(keyword_condition)
        if bbox:
            bbox_condition = _bbox_condition(layer, bbox, params, index)
            if bbox_condition:
                conditions.append(bbox_condition)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        selects.append(
            "SELECT "
            f"CAST(:{layer_param} AS TEXT) AS layer_id, "
            f"CAST(:{order_param} AS INTEGER) AS layer_order, "
            f"CAST(w.{key} AS TEXT) AS feature_key, "
            f"CAST(:{class_param} AS TEXT) AS object_class, "
            f"{_name_expr(layer)} AS name, "
            f"{_name_field_expr(layer)} AS name_field, "
            f"{_inform_expr(layer)} AS inform, "
            f"{status} AS status, "
            f"{geometry} AS geometry "
            f"FROM {table} AS w{where}"
        )
    if not selects:
        return "", "", {}
    union = " UNION ALL ".join(selects)
    count_sql = f"SELECT COUNT(*) FROM ({union}) AS waterway_hits"
    rows_sql = (
        "SELECT * FROM ("
        + union
        + ") AS waterway_hits ORDER BY layer_order, feature_key "
        "LIMIT :limit OFFSET :offset"
    )
    params["limit"] = payload.page_size
    params["offset"] = (payload.page - 1) * payload.page_size
    return count_sql, rows_sql, params


def _apply_statement_timeout(db: Session) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    timeout = str(get_settings().s57_waterway_query_timeout_ms)
    try:
        # The default Docker /dev/shm (64 MiB) is too small for PostgreSQL
        # parallel workers on a multi-layer UNION with large geometries.
        # Disable parallel execution for this read-only thematic query and
        # keep the statement bounded by a timeout.
        db.execute(
            text(
                "SELECT set_config('statement_timeout', :timeout, true), "
                "set_config('max_parallel_workers_per_gather', '0', true), "
                "set_config('max_parallel_workers', '0', true)"
            ),
            {"timeout": timeout},
        )
    except DBAPIError:
        logger.warning("无法设置 S-57 航道查询会话参数", exc_info=True)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _geometry_bbox(geometry: dict[str, Any] | None) -> list[float] | None:
    if not geometry:
        return None
    xs: list[float] = []
    ys: list[float] = []

    def visit(value: Any) -> None:
        if isinstance(value, (list, tuple)) and len(value) >= 2 and all(
            isinstance(item, (int, float)) for item in value[:2]
        ):
            xs.append(float(value[0]))
            ys.append(float(value[1]))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(geometry.get("coordinates"))
    if not xs or not ys:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _row_item(row: dict[str, Any], layer: WaterwayLayerRef) -> dict[str, Any]:
    raw_geometry = row.get("geometry")
    geometry = json.loads(raw_geometry) if raw_geometry else None
    name = row.get("name")
    inform = row.get("inform")
    feature_key = str(row.get("feature_key") or "")
    return {
        "id": encode_waterway_id(layer.layer_id, feature_key),
        "layerId": str(layer.layer_id),
        "layerName": layer.layer_name,
        "layerCode": layer.layer_code,
        "datasetCode": layer.dataset_code,
        "datasetName": layer.dataset_name,
        "versionNo": layer.version_no,
        "sourceCell": layer.source_cell,
        "objectClass": layer.object_class,
        "objectNameZh": layer.rule.name_zh,
        "group": layer.rule.group,
        "groupNameZh": layer.rule.group_name_zh,
        "auxiliary": layer.rule.auxiliary,
        "name": str(name) if name else None,
        "nameField": row.get("name_field") or None,
        "inform": str(inform)[:500] if inform else None,
        "status": row.get("status") or None,
        "geometryType": (geometry or {}).get("type") or layer.geometry_type,
        "renderable": bool(layer.renderable and geometry),
        "geometry": geometry,
        "bbox": _geometry_bbox(geometry),
    }


def encode_waterway_id(layer_id: UUID, feature_key: str) -> str:
    payload = json.dumps(
        {"l": str(layer_id), "k": str(feature_key)}, separators=(",", ":")
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_waterway_id(value: str) -> tuple[UUID, str]:
    if not value or len(value) > 512:
        raise AppError("S57_WATERWAY_FEATURE_NOT_FOUND", "航道要素不存在", 404)
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        layer_id = UUID(str(payload["l"]))
        feature_key = str(payload["k"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AppError("S57_WATERWAY_FEATURE_NOT_FOUND", "航道要素不存在", 404) from exc
    if not feature_key or len(feature_key) > 256:
        raise AppError("S57_WATERWAY_FEATURE_NOT_FOUND", "航道要素不存在", 404)
    return layer_id, feature_key


def _db_error(error: DBAPIError) -> AppError:
    pgcode = getattr(getattr(error, "orig", None), "pgcode", None)
    if pgcode == "53100" or "shared memory" in str(error).lower() or "diskfull" in str(error).lower():
        return AppError(
            "S57_WATERWAY_DB_UNAVAILABLE",
            "数据库共享内存不足，请稍后重试或联系管理员调整 PostgreSQL 配置",
            503,
        )
    if pgcode == "57014" or "statement timeout" in str(error).lower():
        return AppError(
            "S57_WATERWAY_QUERY_TIMEOUT",
            "航道专题查询超时，请缩小搜索范围或减少对象类别",
            504,
        )
    logger.warning("S-57 航道查询失败", exc_info=True)
    return AppError("S57_WATERWAY_QUERY_FAILED", "航道专题查询失败", 500)


def execute_waterway_search(db: Session, project_id: UUID, payload: Any) -> dict[str, Any]:
    settings = get_settings()
    if (payload.page - 1) * payload.page_size > settings.s57_waterway_max_offset:
        raise AppError(
            "S57_WATERWAY_PAGE_INVALID",
            "分页偏移过大，请缩小搜索范围后重新查询",
            422,
        )
    resolution = resolve_waterway_layers(db, project_id)
    selected, warnings = _selected_codes(payload)
    warnings.extend(resolution.warnings)
    layers = [layer for layer in resolution.layers if layer.object_class in selected]
    present_classes = {layer.object_class for layer in layers}
    missing = sorted(selected - present_classes)
    if missing:
        warnings.append(f"项目中没有以下类别的航道图层：{', '.join(missing)}")
    if layers:
        _apply_statement_timeout(db)
    try:
        count_sql, rows_sql, params = build_waterway_search_sql(layers, payload)
        if not count_sql:
            return {
                "items": [],
                "page": payload.page,
                "pageSize": payload.page_size,
                "total": 0,
                "truncatedLayers": resolution.truncated,
                "warnings": warnings,
            }
        total = int(db.scalar(text(count_sql), params) or 0)
        rows = db.execute(text(rows_sql), params).mappings().all()
    except DBAPIError as error:
        raise _db_error(error) from error
    layer_by_id = {str(layer.layer_id): layer for layer in layers}
    items = [
        _row_item(dict(row), layer_by_id[str(row["layer_id"])])
        for row in rows
        if str(row["layer_id"]) in layer_by_id
    ]
    return {
        "items": items,
        "page": payload.page,
        "pageSize": payload.page_size,
        "total": total,
        "truncatedLayers": resolution.truncated,
        "warnings": warnings,
    }


def _property_rows(layer: WaterwayLayerRef, row: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw = {field: _json_safe(row.get(field)) for field in layer.fields if field in row}
    properties: list[dict[str, Any]] = []
    for field in CURATED_FIELD_ORDER:
        value = raw.get(field)
        provided = field in layer.fields and value not in (None, "")
        properties.append(
            {
                "field": field.upper(),
                "labelZh": field_label(field, layer.object_class),
                "raw": value,
                "provided": provided,
                "description": FIELD_DESCRIPTIONS.get(field),
                "source": "S-57 属性" if provided else None,
            }
        )
    for field in sorted(field for field in layer.fields if field.startswith("cat")):
        value = raw.get(field)
        properties.append(
            {
                "field": field.upper(),
                "labelZh": field_label(field, layer.object_class),
                "raw": value,
                "provided": field in layer.fields and value not in (None, ""),
                "description": "S-57 类别属性；含义随对象类别定义，当前仅展示原始代码",
                "source": "S-57 属性（原始代码，未翻译）",
            }
        )
    return properties, raw


def get_waterway_feature(db: Session, project_id: UUID, feature_id: str) -> dict[str, Any]:
    layer_id, feature_key = decode_waterway_id(feature_id)
    resolution = resolve_waterway_layers(db, project_id)
    layer = next((item for item in resolution.layers if item.layer_id == layer_id), None)
    if layer is None or not layer.searchable or not layer.key_column:
        raise AppError(
            "S57_WATERWAY_FEATURE_NOT_FOUND",
            "航道要素不存在或图层已不是当前版本，请重新搜索",
            404,
        )
    table = _safe_table(layer.source_table)
    selected = ", ".join(
        f"w.{_quote_identifier(field)} AS {_quote_identifier(field)}" for field in layer.fields
    )
    geometry = (
        f"ST_AsGeoJSON(ST_Transform(w.{_quote_identifier(layer.geometry_column)}, 4326))"
        if layer.geometry_column
        else "NULL::text"
    )
    select_sql = f"SELECT {selected}{', ' if selected else ''}{geometry} AS geometry "
    sql = (
        f"{select_sql}FROM {table} AS w "
        f"WHERE w.{_quote_identifier(layer.key_column)} = :feature_key LIMIT 1"
    )
    key: Any = feature_key
    if layer.key_type == "int":
        try:
            key = int(feature_key)
        except ValueError as exc:
            raise AppError("S57_WATERWAY_FEATURE_NOT_FOUND", "航道要素不存在", 404) from exc
    _apply_statement_timeout(db)
    try:
        row = db.execute(text(sql), {"feature_key": key}).mappings().first()
    except DBAPIError as error:
        raise _db_error(error) from error
    if row is None:
        raise AppError(
            "S57_WATERWAY_FEATURE_NOT_FOUND",
            "航道要素不存在或图层已更新，请重新搜索",
            404,
        )
    data = dict(row)
    geometry_value = json.loads(data.pop("geometry")) if data.get("geometry") else None
    properties, raw = _property_rows(layer, data)
    updated = layer.updated_at.isoformat() if layer.updated_at else None
    return {
        "id": feature_id,
        "layerId": str(layer.layer_id),
        "layerName": layer.layer_name,
        "layerCode": layer.layer_code,
        "datasetCode": layer.dataset_code,
        "datasetName": layer.dataset_name,
        "versionNo": layer.version_no,
        "sourceCell": layer.source_cell,
        "objectClass": layer.object_class,
        "objectNameZh": layer.rule.name_zh,
        "group": layer.rule.group,
        "groupNameZh": layer.rule.group_name_zh,
        "auxiliary": layer.rule.auxiliary,
        "name": raw.get("objnam") or raw.get("nobjnm"),
        "nameField": (
            "OBJNAM" if raw.get("objnam") else ("NOBJNM" if raw.get("nobjnm") else None)
        ),
        "geometryType": (geometry_value or {}).get("type") or layer.geometry_type,
        "geometry": geometry_value,
        "bbox": _geometry_bbox(geometry_value),
        "updatedAt": updated,
        "properties": properties,
        "rawProperties": raw,
    }
