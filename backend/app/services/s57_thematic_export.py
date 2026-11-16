"""S-57 depth/hazard thematic export: real features, filesystem results.

Each export is a self-contained directory under
``<STORAGE_ROOT>/navigation/s57-thematics/<project_id>/<export_id>/`` with
per-category/per-class GeoJSON volumes (split by Cell when needed), a small
sample preview and a manifest. Results are written atomically and are never
overwritten. No database table or migration is required.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import time
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.s57_project_layers import (
    ProjectS57LayerRef,
    resolve_project_s57_layers,
)
from app.services.s57_thematic_catalog import (
    CATEGORY_NAMES,
    CATEGORY_ORDER,
    THEMATIC_CLASS_RULES,
    ThematicClassRule,
    resolve_thematic_layers,
    thematic_rule_or_other,
)
from app.services.s57_waterways import (
    _apply_statement_timeout,
    _bbox_condition,
    _db_error,
    _geometry_bbox,
    _json_safe,
    _quote_identifier,
    _safe_table,
    normalize_source_cells,
)

THEMATIC_SCHEMA_VERSION = "1.0"
MANIFEST_FILENAME = "manifest.json"
PREVIEW_FILENAME = "preview.geojson"

_EXPORT_ID_PATTERN = re.compile(r"^[0-9A-Za-z_-]{1,80}$")
_SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")


def _root(root: Path | None = None) -> Path:
    return (root or get_settings().resolved_s57_thematic_root).resolve()


def _project_dir(project_id: UUID, root: Path | None = None) -> Path:
    base = _root(root)
    project_dir = (base / str(project_id)).resolve()
    if not project_dir.is_relative_to(base):
        raise AppError("S57_THEMATIC_EXPORT_NOT_FOUND", "专题成果不存在", 404)
    return project_dir


def _export_dir(
    project_id: UUID, export_id: str, root: Path | None = None
) -> Path:
    if not _EXPORT_ID_PATTERN.fullmatch(export_id):
        raise AppError("S57_THEMATIC_EXPORT_NOT_FOUND", "专题成果不存在", 404)
    project_dir = _project_dir(project_id, root)
    export_dir = (project_dir / export_id).resolve()
    if not export_dir.is_relative_to(project_dir):
        raise AppError("S57_THEMATIC_EXPORT_NOT_FOUND", "专题成果不存在", 404)
    return export_dir


def _safe_filename(value: str | None) -> str:
    cleaned = _SAFE_FILENAME_PATTERN.sub("_", value or "").strip("_")
    return cleaned[:60] or "UNKNOWN"


def encode_thematic_id(layer_id: UUID, feature_key: str) -> str:
    payload = json.dumps(
        {"t": "thematic", "l": str(layer_id), "k": str(feature_key)},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


@dataclass
class _FileRecord:
    path: str
    object_class: str
    source_cell: str | None
    layer_id: str
    feature_count: int
    sha256: str
    bytes: int
    part: int = 1


class _GeoJSONWriter:
    """Stream one FeatureCollection to disk with incremental SHA-256."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = path.open("w", encoding="utf-8", newline="\n")
        self.hasher = hashlib.sha256()
        self.count = 0
        self.bytes = 0
        self._first = True
        self._write('{"type":"FeatureCollection","features":[')

    def _write(self, value: str) -> None:
        data = value.encode("utf-8")
        self.handle.write(value)
        self.bytes += len(data)
        self.hasher.update(data)

    def add(self, feature: dict[str, Any]) -> None:
        text_value = json.dumps(
            feature, ensure_ascii=False, separators=(",", ":")
        )
        self._write(("" if self._first else ",") + text_value)
        self._first = False
        self.count += 1

    def close(self) -> tuple[str, int]:
        self._write("]}")
        self.handle.flush()
        self.handle.close()
        return self.hasher.hexdigest(), self.bytes

    def abort(self) -> None:
        try:
            self.handle.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
        self.path.unlink(missing_ok=True)


def build_thematic_export_batch_sql(
    layer: ProjectS57LayerRef,
    payload: Any,
    *,
    after_key: str | None,
    limit: int,
) -> tuple[str, dict[str, Any]]:
    """Build one keyset batch for a generic S-57 thematic layer."""
    if not layer.searchable or not layer.key_column or not layer.geometry_column:
        return "", {}
    params: dict[str, Any] = {}
    table = _safe_table(layer.source_table)
    key = _quote_identifier(layer.key_column)
    geometry = _quote_identifier(layer.geometry_column)
    conditions: list[str] = []
    bbox = getattr(payload, "bbox", None)
    if bbox:
        condition = _bbox_condition(layer, tuple(bbox), params, 0)
        if condition:
            conditions.append(condition)
    if after_key is not None:
        params["after_key"] = after_key
        if layer.key_type == "int":
            conditions.append(f"w.{key} > CAST(:after_key AS BIGINT)")
        else:
            conditions.append(f"w.{key} > :after_key")
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    params["geom_field"] = layer.geometry_column
    params["limit"] = limit
    sql = (
        "SELECT "
        f"CAST(w.{key} AS TEXT) AS feature_key, "
        f"ST_AsGeoJSON(ST_Transform(w.{geometry}, 4326)) AS geometry, "
        f"ST_NDims(w.{geometry}) AS geom_ndim, "
        "to_jsonb(w.*) - CAST(:geom_field AS text) AS raw_attributes "
        f"FROM {table} AS w{where} "
        f"ORDER BY w.{key} "
        "LIMIT :limit"
    )
    return sql, params


def _fetch_rows(
    db: Session, sql: str, params: dict[str, Any]
) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in db.execute(text(sql), params).mappings().all()]
    except DBAPIError as error:
        raise _db_error(error) from error


def _feature_from_row(
    row: dict[str, Any],
    layer: ProjectS57LayerRef,
    rule: ThematicClassRule,
    depth_diagnostic: dict[str, Any] | None,
) -> dict[str, Any] | None:
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
    raw = row.get("raw_attributes") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    if layer.geometry_column:
        raw.pop(layer.geometry_column, None)
    try:
        geometry_ndim = int(row["geom_ndim"]) if row.get("geom_ndim") is not None else None
    except (TypeError, ValueError):
        geometry_ndim = None
    name = raw.get("objnam") or raw.get("nobjnm")
    properties: dict[str, Any] = {
        "objectClass": rule.code,
        "objectNameZh": rule.name_zh,
        "objectName": str(name) if name else None,
        "category": rule.category,
        "categoryNameZh": CATEGORY_NAMES[rule.category],
        "sourceLayerId": str(layer.layer_id),
        "sourceLayerCode": layer.layer_code,
        "sourceLayerName": layer.layer_name,
        "sourceDatasetId": str(layer.dataset_id),
        "sourceDatasetCode": layer.dataset_code,
        "sourceDatasetName": layer.dataset_name,
        "sourceVersionId": str(layer.version_id) if layer.version_id else None,
        "sourceVersionNo": layer.version_no,
        "sourceCell": layer.source_cell,
        "geometryType": (geometry or {}).get("type") or layer.geometry_type,
        "geometryNdim": geometry_ndim,
        "sourceKeyField": layer.key_column.upper() if layer.key_column else None,
        "sourceFeatureKey": feature_key,
        "originalAttributes": _json_safe(raw),
    }
    if rule.code == "SOUNDG":
        depth_sources: list[str] = []
        if geometry_ndim is not None and geometry_ndim >= 3:
            depth_sources.append("geometry_z")
        if "depth" in raw or "depths" in raw:
            depth_sources.append("attribute:DEPTH")
        properties["depthSources"] = depth_sources
        properties["depthUnits"] = "source_unknown"
        properties["depthSign"] = "source_unknown"
        properties["verticalDatum"] = raw.get("verdat") or "未知"
        if depth_sources:
            properties["depthPreserved"] = True
        elif geometry_ndim == 2:
            properties["depthPreserved"] = False
        else:
            properties["depthPreserved"] = (
                depth_diagnostic.get("depthPreserved")
                if depth_diagnostic is not None
                else None
            )
    return {
        "type": "Feature",
        "id": encode_thematic_id(layer.layer_id, feature_key),
        "geometry": geometry,
        "properties": properties,
    }


def _selected_classes(payload: Any) -> list[str]:
    requested = [
        str(code).rsplit(":", maxsplit=1)[-1].strip().upper()
        for code in (getattr(payload, "object_classes", None) or [])
        if str(code).strip()
    ]
    if not requested:
        raise AppError(
            "S57_THEMATIC_CLASS_INVALID",
            "请至少选择一个 S-57 对象类",
            422,
        )
    return list(dict.fromkeys(requested))


def _filter_layers(
    resolution_layers: tuple[ProjectS57LayerRef, ...],
    payload: Any,
    selected: list[str],
    warnings: list[str],
) -> list[ProjectS57LayerRef]:
    actual_classes = {layer.object_class for layer in resolution_layers}
    unknown = [
        code
        for code in selected
        if code not in THEMATIC_CLASS_RULES and code not in actual_classes
    ]
    if unknown:
        raise AppError(
            "S57_THEMATIC_CLASS_INVALID",
            "以下对象类未导入或不受支持：" + ", ".join(unknown),
            422,
        )
    missing = sorted(set(selected) - actual_classes)
    if missing:
        warnings.append(
            "当前项目没有以下对象类的图层：" + ", ".join(missing)
        )

    requested_cells = normalize_source_cells(
        getattr(payload, "source_cells", None)
    )
    dataset_ids = {
        str(item) for item in (getattr(payload, "dataset_ids", None) or [])
    }
    bbox = getattr(payload, "bbox", None)
    layers = [
        layer for layer in resolution_layers if layer.object_class in set(selected)
    ]
    if requested_cells:
        layers = [
            layer for layer in layers if layer.matches_source_cells(requested_cells)
        ]
    if dataset_ids:
        layers = [
            layer for layer in layers if str(layer.dataset_id) in dataset_ids
        ]
    if bbox:
        spatial_layers = [layer for layer in layers if layer.geometry_column]
        missing_geometry = len(layers) - len(spatial_layers)
        if missing_geometry:
            warnings.append(
                f"{missing_geometry} 个图层没有几何列，视口筛选下已跳过"
            )
        layers = spatial_layers
    return layers


def _layer_output_relpath(
    rule: ThematicClassRule,
    layer: ProjectS57LayerRef,
    class_layer_count: int,
    part: int,
) -> str:
    if class_layer_count <= 1:
        base = rule.code
    else:
        base = (
            f"{rule.code}_{_safe_filename(layer.source_cell)}_"
            f"{str(layer.layer_id)[:8]}"
        )
    filename = f"{base}.geojson" if part <= 1 else f"{base}.part{part:03d}.geojson"
    return f"{rule.category}/{filename}"


def _probe_layer_after(
    db: Session,
    layer: ProjectS57LayerRef,
    payload: Any,
    after_key: str | None,
) -> bool:
    sql, params = build_thematic_export_batch_sql(
        layer, payload, after_key=after_key, limit=1
    )
    if not sql:
        return False
    return bool(_fetch_rows(db, sql, params))


def _extend_bbox(
    current: tuple[float, float, float, float] | None,
    geometry: dict[str, Any] | None,
) -> tuple[float, float, float, float] | None:
    bbox = _geometry_bbox(geometry)
    if bbox is None:
        return current
    if current is None:
        return (bbox[0], bbox[1], bbox[2], bbox[3])
    return (
        min(current[0], bbox[0]),
        min(current[1], bbox[1]),
        max(current[2], bbox[2]),
        max(current[3], bbox[3]),
    )


def _source_provenance(
    layers: list[ProjectS57LayerRef],
) -> tuple[list[dict[str, Any]], list[str], dict[str, str]]:
    entries: dict[str, dict[str, Any]] = {}
    version_ids: set[str] = set()
    content_hashes: dict[str, str] = {}
    for layer in layers:
        key = str(layer.dataset_id)
        entry = entries.setdefault(
            key,
            {
                "datasetId": key,
                "datasetCode": layer.dataset_code,
                "datasetName": layer.dataset_name,
                "versionId": str(layer.version_id) if layer.version_id else None,
                "versionNo": layer.version_no,
                "sourceCell": layer.source_cell,
                "layerIds": [],
                "contentHash": layer.content_hash,
            },
        )
        layer_id = str(layer.layer_id)
        if layer_id not in entry["layerIds"]:
            entry["layerIds"].append(layer_id)
        if layer.version_id:
            version_ids.add(str(layer.version_id))
            if layer.content_hash:
                content_hashes[str(layer.version_id)] = layer.content_hash
    return (
        sorted(entries.values(), key=lambda item: str(item["datasetCode"])),
        sorted(version_ids),
        content_hashes,
    )


def _write_manifest(
    temp_dir: Path,
    manifest: dict[str, Any],
) -> None:
    path = temp_dir / MANIFEST_FILENAME
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_thematic_export(
    db: Session, project_id: UUID, payload: Any
) -> dict[str, Any]:
    settings = get_settings()
    resolution = resolve_thematic_layers(db, project_id)
    warnings = list(resolution.warnings)
    selected = _selected_classes(payload)
    layers = _filter_layers(resolution.layers, payload, selected, warnings)

    extractable_all = [
        layer
        for layer in layers
        if layer.searchable and layer.geometry_column and layer.geometry_type
    ]
    skipped_layers: list[dict[str, Any]] = []
    for layer in layers:
        if layer not in extractable_all:
            skipped_layers.append(
                {
                    "layerId": str(layer.layer_id),
                    "layerCode": layer.layer_code,
                    "objectClass": layer.object_class,
                    "reason": layer.reason or "没有可提取的几何/查询能力",
                }
            )
    if not extractable_all:
        raise AppError(
            "S57_THEMATIC_NO_LAYER",
            "没有可提取的 S-57 专题图层，请检查对象类别、来源或视口",
            422,
        )

    class_order = [
        code
        for code in THEMATIC_CLASS_RULES
        if code in selected
    ]
    class_order.extend(
        sorted(
            code
            for code in selected
            if code not in THEMATIC_CLASS_RULES
        )
    )
    class_layers = {
        code: [
            layer for layer in extractable_all if layer.object_class == code
        ]
        for code in class_order
    }

    per_class_cap = max(
        1,
        min(
            int(
                getattr(payload, "max_features_per_class", None)
                or settings.s57_thematic_max_features_per_class
            ),
            settings.s57_thematic_max_features_per_class,
        ),
    )
    total_cap = max(1, settings.s57_thematic_max_features)
    per_file_cap = max(1, settings.s57_thematic_max_features_per_file)
    batch_size = max(1, settings.s57_thematic_batch_size)
    deadline = time.monotonic() + max(1, settings.s57_thematic_export_timeout_seconds)

    created_at = datetime.now(UTC)
    export_id = f"{created_at.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    final_dir = _export_dir(project_id, export_id)
    temp_dir = final_dir.parent / f".{export_id}.tmp"
    temp_dir.mkdir(parents=True, exist_ok=False)

    files: list[_FileRecord] = []
    preview_features: list[dict[str, Any]] = []
    class_stats: dict[str, dict[str, Any]] = {}
    cell_counts: Counter[str] = Counter()
    total_count = 0
    total_bbox: tuple[float, float, float, float] | None = None
    truncated_reasons: list[str] = []
    time_truncated = False
    total_truncated = False
    written_layers: list[ProjectS57LayerRef] = []
    last_class_index = -1
    last_layer_index_global = -1
    last_after_key_global: str | None = None
    active_writer: _GeoJSONWriter | None = None

    try:
        _apply_statement_timeout(db, settings.s57_waterway_snapshot_timeout_ms)
        for class_index, code in enumerate(class_order):
            rule = thematic_rule_or_other(code)
            layers_for_class = class_layers.get(code, [])
            class_written = 0
            class_truncated = False
            last_layer_index = -1
            last_after_key: str | None = None
            for layer_index, layer in enumerate(layers_for_class):
                if time_truncated or total_truncated:
                    break
                # Release AccessShareLocks from the previous table. A project
                # can expose thousands of geo.* tables; one long transaction
                # would exceed PostgreSQL's lock table.
                db.rollback()
                _apply_statement_timeout(
                    db, settings.s57_waterway_snapshot_timeout_ms
                )
                writer: _GeoJSONWriter | None = None
                part = 1
                rel_path = ""
                after_key: str | None = None
                while True:
                    if time.monotonic() > deadline:
                        time_truncated = True
                        break
                    remaining_class = per_class_cap - class_written
                    remaining_total = total_cap - total_count
                    if remaining_class <= 0 or remaining_total <= 0:
                        break
                    limit = min(
                        batch_size,
                        max(1, remaining_class + 1),
                        max(1, remaining_total + 1),
                    )
                    sql, params = build_thematic_export_batch_sql(
                        layer, payload, after_key=after_key, limit=limit
                    )
                    if not sql:
                        break
                    rows = _fetch_rows(db, sql, params)
                    if not rows:
                        break
                    for row in rows:
                        if time.monotonic() > deadline:
                            time_truncated = True
                            break
                        if class_written >= per_class_cap:
                            class_truncated = True
                            break
                        if total_count >= total_cap:
                            total_truncated = True
                            break
                        feature = _feature_from_row(
                            row,
                            layer,
                            rule,
                            resolution.depth_by_layer.get(str(layer.layer_id)),
                        )
                        if feature is None:
                            continue
                        if writer is None or writer.count >= per_file_cap:
                            if writer is not None:
                                sha, size = writer.close()
                                active_writer = None
                                files.append(
                                    _FileRecord(
                                        path=rel_path,
                                        object_class=code,
                                        source_cell=layer.source_cell,
                                        layer_id=str(layer.layer_id),
                                        feature_count=writer.count,
                                        sha256=sha,
                                        bytes=size,
                                        part=part,
                                    )
                                )
                                part += 1
                            rel_path = _layer_output_relpath(
                                rule, layer, len(layers_for_class), part
                            )
                            target = temp_dir / rel_path
                            target.parent.mkdir(parents=True, exist_ok=True)
                            writer = _GeoJSONWriter(target)
                            active_writer = writer
                        writer.add(feature)
                        class_written += 1
                        total_count += 1
                        cell_counts[layer.source_cell or "UNKNOWN"] += 1
                        total_bbox = _extend_bbox(
                            total_bbox, feature.get("geometry")
                        )
                        if (
                            len(preview_features)
                            < settings.s57_thematic_preview_max_features
                            and sum(
                                1
                                for item in preview_features
                                if item["properties"].get("objectClass") == code
                            )
                            < settings.s57_thematic_preview_per_class
                        ):
                            preview_features.append(
                                {
                                    "type": "Feature",
                                    "id": feature["id"],
                                    "geometry": feature["geometry"],
                                    "properties": {
                                        **feature["properties"],
                                        "previewSample": True,
                                    },
                                }
                            )
                    if class_truncated or total_truncated or time_truncated:
                        break
                    after_key = str(rows[-1]["feature_key"])
                    last_layer_index = layer_index
                    last_after_key = after_key
                    last_class_index = class_index
                    last_layer_index_global = layer_index
                    last_after_key_global = after_key
                    if len(rows) < limit:
                        break
                if writer is not None:
                    sha, size = writer.close()
                    active_writer = None
                    files.append(
                        _FileRecord(
                            path=rel_path,
                            object_class=code,
                            source_cell=layer.source_cell,
                            layer_id=str(layer.layer_id),
                            feature_count=writer.count,
                            sha256=sha,
                            bytes=size,
                            part=part,
                        )
                    )
                    written_layers.append(layer)
                if class_truncated or total_truncated or time_truncated:
                    break
            if (
                class_written >= per_class_cap
                and not class_truncated
                and not time_truncated
                and not total_truncated
            ):
                for index in range(
                    max(0, last_layer_index), len(layers_for_class)
                ):
                    probe_layer = layers_for_class[index]
                    probe_after = last_after_key if index == last_layer_index else None
                    if _probe_layer_after(db, probe_layer, payload, probe_after):
                        class_truncated = True
                        break
            if time_truncated:
                class_truncated = True
            if class_truncated and class_written >= per_class_cap:
                truncated_reasons.append("per_class_cap")
                warnings.append(
                    f"{code} 达到单类提取上限 {per_class_cap}，成果已标记截断"
                )
            if total_truncated:
                truncated_reasons.append("total_cap")
                warnings.append(
                    f"成果达到总提取上限 {total_cap}，已标记截断"
                )
            if time_truncated:
                truncated_reasons.append("time_budget")
                warnings.append(
                    "专题提取达到时间预算，成果已标记为不完整；"
                    "请按 Cell/对象类/视口缩小范围后重试"
                )
            class_stats[code] = {
                "code": code,
                "nameZh": rule.name_zh,
                "category": rule.category,
                "categoryNameZh": CATEGORY_NAMES[rule.category],
                "featureCount": class_written,
                "truncated": class_truncated,
                "layerCount": len(layers_for_class),
            }
            if total_truncated or time_truncated:
                break

        # Probe only positions that were not already written when the total cap
        # was hit exactly at a batch/layer boundary. This avoids the false
        # positive of re-reading already exported rows.
        if total_count >= total_cap and not total_truncated and not time_truncated:
            for ci in range(max(0, last_class_index), len(class_order)):
                code = class_order[ci]
                start_layer = (
                    last_layer_index_global if ci == last_class_index else 0
                )
                for li in range(
                    max(0, start_layer), len(class_layers.get(code, []))
                ):
                    after_key = (
                        last_after_key_global
                        if ci == last_class_index and li == start_layer
                        else None
                    )
                    if _probe_layer_after(
                        db, class_layers[code][li], payload, after_key
                    ):
                        total_truncated = True
                        break
                if total_truncated:
                    break
            if total_truncated:
                truncated_reasons.append("total_cap")
                warnings.append(
                    f"成果达到总提取上限 {total_cap}，已标记截断"
                )

        if total_count == 0:
            raise AppError(
                "S57_THEMATIC_NO_FEATURE",
                "没有匹配的 S-57 专题要素，未创建成果",
                422,
            )

        preview_manifest: dict[str, Any] | None = None
        if preview_features:
            preview_bytes = json.dumps(
                {"type": "FeatureCollection", "features": preview_features},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            (temp_dir / PREVIEW_FILENAME).write_bytes(preview_bytes)
            preview_manifest = {
                "path": PREVIEW_FILENAME,
                "featureCount": len(preview_features),
                "sha256": hashlib.sha256(preview_bytes).hexdigest(),
                "sample": True,
            }

        source_layers = written_layers or extractable_all
        source_datasets, source_version_ids, source_content_hashes = (
            _source_provenance(source_layers)
        )
        total_truncated = total_truncated or any(
            stat["truncated"] for stat in class_stats.values()
        )
        complete = not (total_truncated or time_truncated)
        if complete:
            truncated_reasons = []
        else:
            truncated_reasons = list(dict.fromkeys(truncated_reasons))

        soundg_diagnostics = [
            resolution.depth_by_layer[str(layer.layer_id)]
            for layer in extractable_all
            if layer.object_class == "SOUNDG"
            and str(layer.layer_id) in resolution.depth_by_layer
        ]
        known_depth_states = [
            item.get("depthPreserved")
            for item in soundg_diagnostics
            if item.get("depthPreserved") is not None
        ]
        if any(state is False for state in known_depth_states):
            depth_preserved: bool | None = False
        elif known_depth_states and all(state is True for state in known_depth_states):
            depth_preserved = True
        else:
            depth_preserved = None

        manifest: dict[str, Any] = {
            "schemaVersion": THEMATIC_SCHEMA_VERSION,
            "exportId": export_id,
            "projectId": str(project_id),
            "name": (getattr(payload, "name", None) or "").strip()
            or f"S-57 专题成果 {created_at:%Y-%m-%d %H:%M}",
            "createdAt": created_at.isoformat(),
            "crs": "EPSG:4326",
            "categories": [
                category
                for category in CATEGORY_ORDER
                if any(stat["category"] == category for stat in class_stats.values())
            ],
            "filters": {
                "objectClasses": selected,
                "sourceCells": sorted(
                    normalize_source_cells(
                        getattr(payload, "source_cells", None)
                    )
                )
                or None,
                "datasetIds": sorted(
                    str(item)
                    for item in (getattr(payload, "dataset_ids", None) or [])
                )
                or None,
                "bbox": list(getattr(payload, "bbox", None) or []) or None,
                "maxFeaturesPerClass": per_class_cap,
            },
            "bbox": list(total_bbox) if total_bbox else None,
            "featureCount": total_count,
            "featureCountUnit": (
                "S-57 features; one SOUNDG feature may contain multiple soundings"
            ),
            "complete": complete,
            "truncated": not complete,
            "truncationReasons": truncated_reasons,
            "objectClasses": [
                class_stats[code] for code in class_order if code in class_stats
            ],
            "classCounts": {
                code: stat["featureCount"]
                for code, stat in class_stats.items()
            },
            "cellCounts": dict(sorted(cell_counts.items())),
            "files": [
                {
                    "path": item.path,
                    "objectClass": item.object_class,
                    "sourceCell": item.source_cell,
                    "layerId": item.layer_id,
                    "featureCount": item.feature_count,
                    "sha256": item.sha256,
                    "bytes": item.bytes,
                    "part": item.part,
                }
                for item in files
            ],
            "sourceDatasets": source_datasets,
            "sourceVersionIds": source_version_ids,
            "sourceContentHashes": source_content_hashes,
            "sourceCells": sorted(cell_counts),
            "skippedLayers": skipped_layers,
            "depth": {
                "soundgGeometryNdims": [
                    item.get("geometryNdims") for item in soundg_diagnostics
                ],
                "depthPreserved": depth_preserved,
                "zMin": min(
                    (
                        item["zMin"]
                        for item in soundg_diagnostics
                        if item.get("zMin") is not None
                    ),
                    default=None,
                ),
                "zMax": max(
                    (
                        item["zMax"]
                        for item in soundg_diagnostics
                        if item.get("zMax") is not None
                    ),
                    default=None,
                ),
                "layers": soundg_diagnostics,
                "note": (
                    "SOUNDG 深度可能来自几何 Z 或 DEPTH 属性；单位/符号/垂直基准"
                    "以源 S-57 为准，不作为保证安全水深。"
                ),
            },
            "preview": preview_manifest,
            "semantics": [
                "DRVAL1/DRVAL2/VALDCO/VALSOU 不等于航道保证安全水深。",
                "疏浚/扫测/未测区/数据质量对象不视为可靠实测水深。",
                "专题成果是航线规划的原始候选数据，不是经过安全论证的通航网络。",
            ],
            "warnings": warnings,
        }
        _write_manifest(temp_dir, manifest)
        os.replace(temp_dir, final_dir)
    except Exception:
        if active_writer is not None:
            active_writer.abort()
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return {**manifest, "stale": False}


def load_thematic_export(
    project_id: UUID, export_id: str, root: Path | None = None
) -> dict[str, Any]:
    path = _export_dir(project_id, export_id, root) / MANIFEST_FILENAME
    if not path.is_file():
        raise AppError("S57_THEMATIC_EXPORT_NOT_FOUND", "专题成果不存在", 404)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AppError(
            "S57_THEMATIC_EXPORT_NOT_FOUND", "专题成果元数据不可读", 404
        ) from exc
    if not isinstance(data, dict) or data.get("exportId") != export_id:
        raise AppError(
            "S57_THEMATIC_EXPORT_NOT_FOUND", "专题成果元数据格式无效", 404
        )
    return data


def list_thematic_exports(
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
        if not _EXPORT_ID_PATTERN.fullmatch(child.name):
            continue
        try:
            manifest = load_thematic_export(project_id, child.name, root)
        except AppError:
            warnings.append(f"专题成果 {child.name} 元数据损坏，已跳过")
            continue
        items.append(manifest)
    items.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    return items, warnings


def current_thematic_version_ids(db: Session, project_id: UUID) -> set[str]:
    resolution = resolve_project_s57_layers(db, project_id)
    return {
        str(layer.version_id)
        for layer in resolution.layers
        if layer.version_id is not None
    }


def mark_thematic_export_stale(
    manifest: dict[str, Any], current_version_ids: set[str]
) -> dict[str, Any]:
    versions = {
        str(version)
        for version in (manifest.get("sourceVersionIds") or [])
        if version
    }
    return {**manifest, "stale": bool(versions - current_version_ids)}


def _allowed_relative_paths(manifest: dict[str, Any]) -> set[str]:
    paths = {
        str(item.get("path"))
        for item in (manifest.get("files") or [])
        if item.get("path")
    }
    preview = manifest.get("preview")
    if isinstance(preview, dict) and preview.get("path"):
        paths.add(str(preview["path"]))
    return paths


def thematic_file_path(
    project_id: UUID,
    export_id: str,
    relative_path: str,
    root: Path | None = None,
) -> Path:
    manifest = load_thematic_export(project_id, export_id, root)
    allowed = _allowed_relative_paths(manifest)
    pure = PurePosixPath(relative_path)
    if (
        relative_path not in allowed
        or pure.is_absolute()
        or ".." in pure.parts
        or "\\" in relative_path
    ):
        raise AppError("S57_THEMATIC_EXPORT_NOT_FOUND", "专题成果文件不存在", 404)
    export_dir = _export_dir(project_id, export_id, root)
    path = (export_dir / pure).resolve()
    if not path.is_relative_to(export_dir) or not path.is_file():
        raise AppError("S57_THEMATIC_EXPORT_NOT_FOUND", "专题成果文件不存在", 404)
    return path


def build_thematic_zip(
    project_id: UUID, export_id: str, root: Path | None = None
) -> tuple[Path, str]:
    manifest = load_thematic_export(project_id, export_id, root)
    export_dir = _export_dir(project_id, export_id, root)
    zip_path = export_dir.parent / f".{export_id}.{secrets.token_hex(4)}.zip"
    with zipfile.ZipFile(
        zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        archive.write(
            export_dir / MANIFEST_FILENAME, arcname=MANIFEST_FILENAME
        )
        for item in manifest.get("files") or []:
            relative = str(item.get("path") or "")
            if not relative:
                continue
            source = thematic_file_path(project_id, export_id, relative, root)
            archive.write(source, arcname=relative)
        preview = manifest.get("preview")
        if isinstance(preview, dict) and preview.get("path"):
            relative = str(preview["path"])
            source = thematic_file_path(project_id, export_id, relative, root)
            archive.write(source, arcname=relative)
    filename = f"s57-thematic-{export_id}.zip"
    return zip_path, filename
