"""S-57 waterway snapshot extraction, persistence and GeoJSON download.

Snapshots are read from the already imported PostGIS ``geo.*`` tables through
:mod:`app.services.s57_waterways` — no ``.000`` re-import is performed. Each
snapshot is written atomically under the persistent shared storage volume:

``<storage_root>/navigation/waterways/<project_id>/<snapshot_id>/``
    ``waterways.geojson``
    ``manifest.json``

The GeoJSON keeps the real geometry type and every original attribute, in
EPSG:4326 ``[lon, lat]`` coordinates, so later planning scripts can load it
with ``json.load`` without touching the database.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.s57_waterway_catalog import WATERWAY_CLASS_RULES
from app.services.s57_waterways import (
    WaterwayLayerRef,
    _apply_statement_timeout,
    _db_error,
    _geometry_bbox,
    _json_safe,
    _selected_codes,
    build_waterway_count_sql,
    build_waterway_export_batch_sql,
    encode_waterway_id,
    layer_matches_source_cells,
    normalize_source_cells,
    resolve_waterway_layers,
)

SNAPSHOT_SCHEMA_VERSION = "1.0"
GEOJSON_FILENAME = "waterways.geojson"
MANIFEST_FILENAME = "manifest.json"

_SNAPSHOT_ID_PATTERN = re.compile(r"^[0-9A-Za-z_-]{1,80}$")
_CURSOR_MAX_LENGTH = 512
_CURSOR_KEY_MAX_LENGTH = 256

logger = logging.getLogger(__name__)


def _snapshot_root(root: Path | None = None) -> Path:
    return (root or get_settings().resolved_s57_waterway_snapshot_root).resolve()


def _project_dir(project_id: UUID, root: Path | None = None) -> Path:
    base = _snapshot_root(root)
    project_dir = (base / str(project_id)).resolve()
    if not project_dir.is_relative_to(base):
        raise AppError("S57_WATERWAY_SNAPSHOT_NOT_FOUND", "航道数据成果不存在", 404)
    return project_dir


def _snapshot_dir(project_id: UUID, snapshot_id: str, root: Path | None = None) -> Path:
    if not _SNAPSHOT_ID_PATTERN.fullmatch(snapshot_id):
        raise AppError("S57_WATERWAY_SNAPSHOT_NOT_FOUND", "航道数据成果不存在", 404)
    project_dir = _project_dir(project_id, root)
    snapshot_dir = (project_dir / snapshot_id).resolve()
    if not snapshot_dir.is_relative_to(project_dir):
        raise AppError("S57_WATERWAY_SNAPSHOT_NOT_FOUND", "航道数据成果不存在", 404)
    return snapshot_dir


def _feature_from_row(row: dict[str, Any], layer: WaterwayLayerRef) -> dict[str, Any] | None:
    feature_key = str(row.get("feature_key") or "")
    if not feature_key:
        return None
    raw_geometry = row.get("geometry")
    geometry: dict[str, Any] | None = None
    if raw_geometry:
        try:
            parsed = json.loads(raw_geometry)
        except (TypeError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            geometry = parsed

    raw_attributes = row.get("raw_attributes") or {}
    if isinstance(raw_attributes, str):
        try:
            raw_attributes = json.loads(raw_attributes)
        except json.JSONDecodeError:
            raw_attributes = {}
    if not isinstance(raw_attributes, dict):
        raw_attributes = {}
    if layer.geometry_column:
        raw_attributes.pop(layer.geometry_column, None)

    name = row.get("name")
    return {
        "type": "Feature",
        "id": encode_waterway_id(layer.layer_id, feature_key),
        "geometry": geometry,
        "properties": {
            "objectClass": layer.object_class,
            "objectName": str(name) if name else None,
            "objectNameZh": layer.rule.name_zh,
            "group": layer.rule.group,
            "groupNameZh": layer.rule.group_name_zh,
            "auxiliary": layer.rule.auxiliary,
            "sourceLayerId": str(layer.layer_id),
            "sourceLayerCode": layer.layer_code,
            "sourceLayerName": layer.layer_name,
            "sourceDatasetId": str(layer.dataset_id),
            "sourceDatasetCode": layer.dataset_code,
            "sourceDatasetName": layer.dataset_name,
            "sourceVersionId": str(layer.version_id) if layer.version_id else None,
            "sourceVersionNo": layer.version_no,
            "sourceCell": layer.source_cell,
            "sourceKeyField": layer.key_column.upper() if layer.key_column else None,
            "sourceFeatureKey": feature_key,
            "originalAttributes": _json_safe(raw_attributes),
        },
    }


def _source_provenance(
    layers: list[WaterwayLayerRef],
) -> tuple[list[dict[str, Any]], list[str], dict[str, str]]:
    entries: dict[str, dict[str, Any]] = {}
    version_ids: set[str] = set()
    content_hashes: dict[str, str] = {}
    for layer in layers:
        dataset_key = str(layer.dataset_id)
        entry = entries.get(dataset_key)
        if entry is None:
            entry = {
                "datasetId": dataset_key,
                "datasetCode": layer.dataset_code,
                "datasetName": layer.dataset_name,
                "versionId": str(layer.version_id) if layer.version_id else None,
                "versionNo": layer.version_no,
                "sourceCell": layer.source_cell,
                "layerIds": [],
                "contentHash": layer.content_hash,
            }
            entries[dataset_key] = entry
        layer_id = str(layer.layer_id)
        if layer_id not in entry["layerIds"]:
            entry["layerIds"].append(layer_id)
        if layer.version_id:
            version_id = str(layer.version_id)
            version_ids.add(version_id)
            if layer.content_hash:
                content_hashes[version_id] = layer.content_hash
    datasets = sorted(entries.values(), key=lambda item: str(item["datasetCode"]))
    return datasets, sorted(version_ids), content_hashes


def write_snapshot(
    project_id: UUID,
    *,
    name: str | None,
    features: list[dict[str, Any]],
    object_classes: list[str],
    source_datasets: list[dict[str, Any]],
    source_version_ids: list[str],
    source_content_hashes: dict[str, str],
    filters: dict[str, Any],
    warnings: list[str],
    truncated: bool,
    root: Path | None = None,
) -> dict[str, Any]:
    """Atomically persist one GeoJSON snapshot and return its manifest."""
    created_at = datetime.now(UTC)
    snapshot_id = f"{created_at.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    final_dir = _snapshot_dir(project_id, snapshot_id, root)
    temp_dir = final_dir.parent / f".{snapshot_id}.tmp"

    feature_collection = {"type": "FeatureCollection", "features": features}
    geojson_bytes = json.dumps(
        feature_collection, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    manifest: dict[str, Any] = {
        "snapshotId": snapshot_id,
        "projectId": str(project_id),
        "name": (name or "").strip() or f"航道成果 {created_at:%Y-%m-%d %H:%M}",
        "createdAt": created_at.isoformat(),
        "crs": "EPSG:4326",
        "featureCount": len(features),
        "truncated": truncated,
        "objectClasses": sorted(object_classes),
        "sourceDatasets": source_datasets,
        "sourceVersionIds": sorted(source_version_ids),
        "sourceContentHashes": source_content_hashes,
        "filters": filters,
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "warnings": list(warnings),
        "geojsonSha256": hashlib.sha256(geojson_bytes).hexdigest(),
    }

    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        (temp_dir / GEOJSON_FILENAME).write_bytes(geojson_bytes)
        (temp_dir / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_dir, final_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return {**manifest, "stale": False}


def _resolve_usable_layers(
    db: Session, project_id: UUID, payload: Any
) -> tuple[list[WaterwayLayerRef], set[str], list[str]]:
    """Resolve current-version waterway layers usable under the request filters."""
    resolution = resolve_waterway_layers(db, project_id)
    selected, warnings = _selected_codes(payload)
    warnings.extend(resolution.warnings)

    layers = [layer for layer in resolution.layers if layer.object_class in selected]
    missing = sorted(selected - {layer.object_class for layer in layers})
    if missing:
        warnings.append(f"项目中没有以下类别的航道图层：{', '.join(missing)}")

    requested_cells = normalize_source_cells(
        getattr(payload, "source_cells", None)
    )
    if requested_cells:
        matching_cells = {
            layer.source_cell.strip().upper()
            for layer in layers
            if layer.source_cell
        }
        missing_cells = sorted(requested_cells - matching_cells)
        if missing_cells:
            warnings.append(
                "当前选择中没有以下海图 Cell：" + ", ".join(missing_cells)
            )
        layers = [
            layer
            for layer in layers
            if layer_matches_source_cells(layer, requested_cells)
        ]

    keyword = (payload.keyword or "").strip()
    usable: list[WaterwayLayerRef] = []
    for layer in layers:
        if not layer.searchable or not layer.key_column:
            warnings.append(f"图层 {layer.layer_code} 缺少可导出的稳定要素标识，已跳过")
            continue
        if keyword and not any(
            field in layer.fields
            for field in ("objnam", "nobjnm", "inform", "ninfom")
        ):
            warnings.append(f"图层 {layer.layer_code} 无名称/补充信息字段，关键词筛选下已跳过")
            continue
        if payload.bbox and not layer.geometry_column:
            warnings.append(f"图层 {layer.layer_code} 无几何列，视口筛选下已跳过")
            continue
        usable.append(layer)
    return usable, selected, warnings


def _extract_features(
    db: Session,
    usable: list[WaterwayLayerRef],
    payload: Any,
    max_features: int,
    batch_size: int,
) -> tuple[list[tuple[WaterwayLayerRef, dict[str, Any]]], bool]:
    """Read matching rows in keyset batches, returning (layer, feature) pairs.

    One extra row is read to prove that truncation is real. A result set whose
    size is exactly ``max_features`` is not reported as truncated when the
    source is exhausted.
    """
    extracted: list[tuple[WaterwayLayerRef, dict[str, Any]]] = []
    target = max_features + 1
    _apply_statement_timeout(db, get_settings().s57_waterway_snapshot_timeout_ms)
    try:
        for layer in usable:
            after_key: str | None = None
            while len(extracted) < target:
                limit = min(batch_size, target - len(extracted))
                sql, params = build_waterway_export_batch_sql(
                    layer, payload, after_key=after_key, limit=limit
                )
                if not sql:
                    break
                rows = db.execute(text(sql), params).mappings().all()
                if not rows:
                    break
                for row in rows:
                    if len(extracted) >= target:
                        break
                    feature = _feature_from_row(dict(row), layer)
                    if feature is not None:
                        extracted.append((layer, feature))
                after_key = str(rows[-1]["feature_key"])
                if len(rows) < limit:
                    break
            if len(extracted) >= target:
                break
    except DBAPIError as error:
        raise _db_error(error) from error
    truncated = len(extracted) > max_features
    return extracted[:max_features], truncated


def encode_preview_cursor(layer_id: UUID, after_key: str) -> str:
    payload = json.dumps(
        {"l": str(layer_id), "k": str(after_key)}, separators=(",", ":")
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_preview_cursor(value: str) -> tuple[UUID, str]:
    if not value or len(value) > _CURSOR_MAX_LENGTH:
        raise AppError(
            "S57_WATERWAY_CURSOR_INVALID",
            "预览游标已失效，请重新加载",
            409,
        )
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        layer_id = UUID(str(payload["l"]))
        after_key = str(payload["k"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AppError(
            "S57_WATERWAY_CURSOR_INVALID",
            "预览游标已失效，请重新加载",
            409,
        ) from exc
    if not after_key or len(after_key) > _CURSOR_KEY_MAX_LENGTH:
        raise AppError(
            "S57_WATERWAY_CURSOR_INVALID",
            "预览游标已失效，请重新加载",
            409,
        )
    return layer_id, after_key


def _extract_class_page(
    db: Session,
    layers: list[WaterwayLayerRef],
    payload: Any,
    limit: int,
    cursor: str | None,
) -> tuple[list[tuple[WaterwayLayerRef, dict[str, Any]]], str | None, bool]:
    """Extract one fair page for a single object class.

    The cursor only identifies the current layer/key; subsequent layers are
    consumed in stable resolution order. One extra row is read to prove
    ``has_more`` without over-reporting truncation.
    """
    if not layers or limit < 1:
        return [], None, False
    batch_size = max(1, get_settings().s57_waterway_snapshot_batch_size)
    start_index = 0
    after_key: str | None = None
    if cursor:
        layer_id, after_key = decode_preview_cursor(cursor)
        found = next(
            (index for index, layer in enumerate(layers) if layer.layer_id == layer_id),
            None,
        )
        if found is None:
            raise AppError(
                "S57_WATERWAY_CURSOR_INVALID",
                "预览游标对应的图层已不是当前版本，请重新加载",
                409,
            )
        start_index = found

    collected: list[tuple[WaterwayLayerRef, dict[str, Any]]] = []
    target = limit + 1
    try:
        for offset, layer in enumerate(layers[start_index:]):
            current_after = after_key if offset == 0 else None
            while len(collected) < target:
                remaining = target - len(collected)
                batch_limit = min(batch_size, remaining)
                sql, params = build_waterway_export_batch_sql(
                    layer, payload, after_key=current_after, limit=batch_limit
                )
                if not sql:
                    break
                rows = db.execute(text(sql), params).mappings().all()
                if not rows:
                    break
                for row in rows:
                    if len(collected) >= target:
                        break
                    feature = _feature_from_row(dict(row), layer)
                    if feature is not None:
                        collected.append((layer, feature))
                current_after = str(rows[-1]["feature_key"])
                if len(rows) < batch_limit:
                    break
            if len(collected) >= target:
                break
    except DBAPIError as error:
        raise _db_error(error) from error

    has_more = len(collected) > limit
    kept = collected[:limit]
    next_cursor: str | None = None
    if has_more and kept:
        last_layer, last_feature = kept[-1]
        last_key = str(
            (last_feature.get("properties") or {}).get("sourceFeatureKey") or ""
        )
        if last_key:
            next_cursor = encode_preview_cursor(last_layer.layer_id, last_key)
    return kept, next_cursor, has_more


def _class_matched_total(
    db: Session,
    layers: list[WaterwayLayerRef],
    payload: Any,
    code: str,
    warnings: list[str],
) -> int | None:
    count_sql, params = build_waterway_count_sql(layers, payload)
    if not count_sql:
        return 0
    try:
        with db.begin_nested():
            return int(db.scalar(text(count_sql), params) or 0)
    except DBAPIError as error:
        # A PostgreSQL statement timeout aborts the current transaction. Use a
        # savepoint so later class queries remain usable.
        pgcode = getattr(getattr(error, "orig", None), "pgcode", None)
        if pgcode == "57014" or "statement timeout" in str(error).lower():
            warnings.append(f"{code} 匹配总数计算超时，显示为“未知”")
        else:
            logger.warning("S-57 航道预览匹配总数计算失败", exc_info=True)
            warnings.append(f"{code} 匹配总数计算失败，显示为“未知”")
        return None


def _empty_preview_response(warnings: list[str]) -> dict[str, Any]:
    return {
        "items": [],
        "total": 0,
        "truncated": False,
        "matchedTotal": 0,
        "returnedCount": 0,
        "hasMore": False,
        "classHasMore": {},
        "nextCursors": {},
        "classMatchedTotals": {},
        "countComplete": True,
        "truncatedLayers": False,
        "groupCounts": {},
        "objectClassCounts": {},
        "warnings": warnings,
    }


def _preview_item(
    layer: WaterwayLayerRef, feature: dict[str, Any]
) -> dict[str, Any]:
    """Convert an extracted feature into the search-item shape used by the map."""
    properties = feature.get("properties") or {}
    geometry = feature.get("geometry")
    raw = properties.get("originalAttributes") or {}
    name = properties.get("objectName")
    if raw.get("objnam"):
        name_field = "OBJNAM"
    elif raw.get("nobjnm"):
        name_field = "NOBJNM"
    else:
        name_field = None
    inform = raw.get("inform") or raw.get("ninfom")
    status = raw.get("status")
    return {
        "id": feature["id"],
        "layerId": properties["sourceLayerId"],
        "layerName": properties["sourceLayerName"],
        "layerCode": properties["sourceLayerCode"],
        "datasetCode": properties["sourceDatasetCode"],
        "datasetName": properties["sourceDatasetName"],
        "versionNo": properties["sourceVersionNo"],
        "sourceCell": properties["sourceCell"],
        "objectClass": properties["objectClass"],
        "objectNameZh": properties["objectNameZh"],
        "group": properties["group"],
        "groupNameZh": properties["groupNameZh"],
        "auxiliary": properties["auxiliary"],
        "name": name,
        "nameField": name_field,
        "inform": str(inform)[:500] if inform else None,
        "status": str(status) if status is not None else None,
        "geometryType": (geometry or {}).get("type") or layer.geometry_type,
        "renderable": bool(layer.renderable and geometry),
        "geometry": geometry,
        "bbox": _geometry_bbox(geometry),
    }


def create_waterway_snapshot(db: Session, project_id: UUID, payload: Any) -> dict[str, Any]:
    """Extract every matching waterway feature and persist it as a snapshot."""
    settings = get_settings()
    usable, selected, warnings = _resolve_usable_layers(db, project_id, payload)
    if not usable:
        raise AppError(
            "S57_WATERWAY_SNAPSHOT_NO_LAYER",
            "没有可提取的航道图层，请检查对象类别与筛选条件",
            422,
        )

    max_features = max(1, settings.s57_waterway_snapshot_max_features)
    if payload.max_features is not None and payload.max_features > max_features:
        warnings.append(f"单次最多提取 {max_features} 个要素，已按上限截取")
    effective_max = min(payload.max_features or max_features, max_features)
    batch_size = max(1, settings.s57_waterway_snapshot_batch_size)

    extracted, truncated = _extract_features(
        db, usable, payload, effective_max, batch_size
    )
    features = [feature for _, feature in extracted]
    if not features:
        raise AppError("S57_WATERWAY_SNAPSHOT_EMPTY", "没有匹配的航道要素", 422)

    source_datasets, source_version_ids, source_content_hashes = _source_provenance(usable)
    filters = {
        "keyword": payload.keyword,
        "objectClasses": sorted(selected),
        "includeAuxiliary": payload.include_auxiliary,
        "bbox": list(payload.bbox) if payload.bbox else None,
        "sourceCells": sorted(
            normalize_source_cells(getattr(payload, "source_cells", None))
        )
        or None,
        "maxFeatures": effective_max,
    }
    return write_snapshot(
        project_id,
        name=payload.name,
        features=features,
        object_classes=sorted(
            {str(feature["properties"]["objectClass"]) for feature in features}
        ),
        source_datasets=source_datasets,
        source_version_ids=source_version_ids,
        source_content_hashes=source_content_hashes,
        filters=filters,
        warnings=warnings,
        truncated=truncated,
    )


def preview_waterway_items(db: Session, project_id: UUID, payload: Any) -> dict[str, Any]:
    """Return one fair, cursor-paged preview page; nothing is written to disk.

    Each selected object class receives an equal share of the request budget,
    so a high-volume class (for example TSSLPT) cannot hide every other class.
    A second pass redistributes unused budget. The response carries per-class
    match totals, cursors and explicit has-more flags.
    """
    settings = get_settings()
    usable, selected, warnings = _resolve_usable_layers(db, project_id, payload)
    if not usable:
        warnings.append("没有可展示的航道图层，请检查对象类别与筛选条件")
        return _empty_preview_response(warnings)

    max_features = max(1, settings.s57_waterway_preview_max_features)
    if payload.max_features is not None and payload.max_features > max_features:
        warnings.append(f"单次最多显示 {max_features} 个要素，已按上限截取")
    effective_max = min(payload.max_features or max_features, max_features)
    _apply_statement_timeout(db)

    class_order = [
        code
        for code in WATERWAY_CLASS_RULES
        if code in selected and any(layer.object_class == code for layer in usable)
    ]
    class_order.extend(
        sorted({layer.object_class for layer in usable} - set(class_order))
    )
    class_layers = {
        code: [layer for layer in usable if layer.object_class == code]
        for code in class_order
    }

    requested_cursors = dict(getattr(payload, "class_cursors", None) or {})
    unknown_cursor_classes = sorted(set(requested_cursors) - set(class_layers))
    if unknown_cursor_classes:
        raise AppError(
            "S57_WATERWAY_CURSOR_INVALID",
            "预览游标对应的对象类别已不可用，请重新加载",
            409,
        )

    class_matched_totals: dict[str, int | None] = {}
    count_complete = True
    for code in class_order:
        total = _class_matched_total(
            db, class_layers[code], payload, code, warnings
        )
        class_matched_totals[code] = total
        if total is None:
            count_complete = False

    cursors: dict[str, str | None] = {
        code: requested_cursors.get(code) for code in class_order
    }
    class_has_more = {code: False for code in class_order}
    exhausted = {code: False for code in class_order}
    processed: set[str] = set()
    collected: dict[str, list[tuple[WaterwayLayerRef, dict[str, Any]]]] = {
        code: [] for code in class_order
    }

    remaining = effective_max
    rounds = 0
    while remaining > 0 and rounds < 2:
        active = [code for code in class_order if not exhausted[code]]
        if not active:
            break
        share = max(1, remaining // len(active))
        progressed = False
        for code in active:
            if remaining <= 0:
                break
            take = min(share, remaining)
            page, next_cursor, has_more = _extract_class_page(
                db,
                class_layers[code],
                payload,
                take,
                cursors.get(code),
            )
            processed.add(code)
            cursors[code] = next_cursor
            class_has_more[code] = has_more
            if not has_more:
                exhausted[code] = True
            if page:
                collected[code].extend(page)
                remaining -= len(page)
                progressed = True
        rounds += 1
        if not progressed:
            break

    # Classes skipped entirely because the budget was exhausted still need a
    # truthful "more" signal; they were not loaded, so the client may request
    # them from the start on the next call.
    for code in class_order:
        if code in processed:
            continue
        matched = class_matched_totals.get(code)
        class_has_more[code] = matched is None or matched != 0

    extracted: list[tuple[WaterwayLayerRef, dict[str, Any]]] = []
    for code in class_order:
        extracted.extend(collected[code])
    items = [_preview_item(layer, feature) for layer, feature in extracted]
    group_counts: dict[str, int] = {}
    class_counts: dict[str, int] = {}
    for item in items:
        group_counts[item["group"]] = group_counts.get(item["group"], 0) + 1
        class_counts[item["objectClass"]] = class_counts.get(item["objectClass"], 0) + 1

    matched_total = (
        sum(value for value in class_matched_totals.values() if value is not None)
        if count_complete
        else None
    )
    has_more = any(class_has_more.values())
    return {
        "items": items,
        "total": matched_total if matched_total is not None else len(items),
        "truncated": has_more,
        "matchedTotal": matched_total,
        "returnedCount": len(items),
        "hasMore": has_more,
        "classHasMore": class_has_more,
        "nextCursors": {
            code: cursor for code, cursor in cursors.items() if cursor
        },
        "classMatchedTotals": class_matched_totals,
        "countComplete": count_complete,
        "truncatedLayers": False,
        "groupCounts": group_counts,
        "objectClassCounts": class_counts,
        "warnings": warnings,
    }


def load_snapshot_manifest(
    project_id: UUID, snapshot_id: str, root: Path | None = None
) -> dict[str, Any]:
    path = _snapshot_dir(project_id, snapshot_id, root) / MANIFEST_FILENAME
    if not path.is_file():
        raise AppError("S57_WATERWAY_SNAPSHOT_NOT_FOUND", "航道数据成果不存在", 404)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AppError(
            "S57_WATERWAY_SNAPSHOT_NOT_FOUND", "航道数据成果元数据不可读", 404
        ) from exc
    if not isinstance(data, dict):
        raise AppError("S57_WATERWAY_SNAPSHOT_NOT_FOUND", "航道数据成果元数据不可读", 404)
    return data


def snapshot_geojson_path(
    project_id: UUID, snapshot_id: str, root: Path | None = None
) -> Path:
    # Validate before exposing a filesystem path; manifest presence is checked
    # separately so an interrupted/incomplete directory cannot be downloaded.
    path = _snapshot_dir(project_id, snapshot_id, root) / GEOJSON_FILENAME
    if not path.is_file():
        raise AppError("S57_WATERWAY_SNAPSHOT_NOT_FOUND", "航道数据成果文件不存在", 404)
    return path


def list_snapshots(
    project_id: UUID, root: Path | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    project_dir = _project_dir(project_id, root)
    warnings: list[str] = []
    if not project_dir.is_dir():
        return [], warnings
    items: list[dict[str, Any]] = []
    for child in sorted(project_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        manifest_path = child / MANIFEST_FILENAME
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            warnings.append(f"快照 {child.name} 元数据损坏，已跳过")
            continue
        if not isinstance(manifest, dict) or manifest.get("snapshotId") != child.name:
            warnings.append(f"快照 {child.name} 元数据格式无效，已跳过")
            continue
        items.append(manifest)
    items.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    return items, warnings


def mark_snapshot_stale(
    manifest: dict[str, Any], current_version_ids: set[str]
) -> dict[str, Any]:
    versions = {
        str(version)
        for version in (manifest.get("sourceVersionIds") or [])
        if version
    }
    return {**manifest, "stale": bool(versions - current_version_ids)}


def current_waterway_version_ids(db: Session, project_id: UUID) -> set[str]:
    resolution = resolve_waterway_layers(db, project_id)
    return {
        str(layer.version_id)
        for layer in resolution.layers
        if layer.version_id is not None
    }
