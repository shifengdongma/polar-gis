"""S-57 depth/hazard thematic taxonomy and project inventory.

The taxonomy is deliberately separate from the waterway thematic and from the
legacy chart-load-profile catalogue. It only describes real, already imported
S-57 object classes; it does not decide whether a depth is safe for navigation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.services.s57_layer_catalog import object_name_for_class
from app.services.s57_project_layers import (
    ProjectS57LayerRef,
    resolve_project_s57_layers,
)
from app.services.s57_waterways import _apply_statement_timeout, _quote_identifier, _safe_table

logger = logging.getLogger(__name__)

CATEGORY_ORDER: Final[tuple[str, ...]] = (
    "depth",
    "depth_supplement",
    "hazards",
    "other",
)

CATEGORY_NAMES: Final = MappingProxyType(
    {
        "depth": "水深与海底地形",
        "depth_supplement": "水深相关补充",
        "hazards": "危险物",
        "other": "其他已导入对象",
    }
)


@dataclass(frozen=True, slots=True)
class ThematicClassRule:
    code: str
    name_zh: str
    category: str
    description: str
    caveats: tuple[str, ...]
    default_selected: bool


def _rule(
    code: str,
    name_zh: str,
    category: str,
    description: str,
    caveats: tuple[str, ...] = (),
    default_selected: bool = False,
) -> ThematicClassRule:
    return ThematicClassRule(
        code=code,
        name_zh=name_zh,
        category=category,
        description=description,
        caveats=caveats,
        default_selected=default_selected,
    )


_DEFINITIONS: Final[tuple[ThematicClassRule, ...]] = (
    _rule(
        "SOUNDG",
        "水深点",
        "depth",
        "S-57 测深点；一条 MultiPoint 要素可包含多个 soundings。",
        (
            "深度可能在几何第三维 Z；单位/符号以源 S-57 为准，不擅自取绝对值或改正负号。",
        ),
        default_selected=True,
    ),
    _rule(
        "DEPCNT",
        "等深线",
        "depth",
        "S-57 等深线，核心属性为 VALDCO。",
        ("VALDCO 是等深线数值。",),
        default_selected=True,
    ),
    _rule(
        "DEPARE",
        "水深区域",
        "depth",
        "S-57 水深区域，核心属性为 DRVAL1/DRVAL2。",
        ("DRVAL1/DRVAL2 是区域水深范围。",),
        default_selected=True,
    ),
    _rule(
        "DRGARE",
        "疏浚区域",
        "depth_supplement",
        "S-57 疏浚区域；按对象语义展示。",
    ),
    _rule(
        "SWPARE",
        "扫测区域",
        "depth_supplement",
        "S-57 扫测区域；表示扫测范围。",
    ),
    _rule(
        "UNSARE",
        "未测量区域",
        "depth_supplement",
        "S-57 未测量区域。",
    ),
    _rule(
        "M_QUAL",
        "数据质量",
        "depth_supplement",
        "S-57 数据质量/置信度信息（如 CATZOC）；按原始属性展示。",
    ),
    _rule(
        "OBSTRN",
        "障碍物",
        "hazards",
        "S-57 障碍物；保留 VALSOU/WATLEV/CATOBS/EXPSOU/QUASOU 等原始属性。",
        ("属性含义随对象类别定义。",),
    ),
    _rule(
        "WRECKS",
        "沉船",
        "hazards",
        "S-57 沉船；保留 VALSOU/WATLEV/CATWRK/QUASOU 等原始属性。",
        ("缺失属性写“未知”。",),
    ),
    _rule(
        "UWTROC",
        "水下或露出水面的礁石",
        "hazards",
        "S-57 水下/露出礁石；保留 VALSOU/WATLEV/EXPSOU/QUASOU 等原始属性。",
        ("缺失属性写“未知”。",),
    ),
)

THEMATIC_CLASS_RULES: Final = MappingProxyType(
    {rule.code: rule for rule in _DEFINITIONS}
)


def classify_thematic(code: str | None) -> ThematicClassRule | None:
    normalized = (code or "").rsplit(":", maxsplit=1)[-1].strip().upper()
    return THEMATIC_CLASS_RULES.get(normalized)


def thematic_rule_or_other(code: str | None) -> ThematicClassRule:
    normalized = (code or "").rsplit(":", maxsplit=1)[-1].strip().upper()
    return THEMATIC_CLASS_RULES.get(normalized) or ThematicClassRule(
        code=normalized or "UNKNOWN",
        name_zh=object_name_for_class(normalized),
        category="other",
        description="其他已导入的 S-57 空间对象类。",
        caveats=(),
        default_selected=False,
    )


@dataclass(frozen=True)
class ThematicResolution:
    layers: tuple[ProjectS57LayerRef, ...]
    warnings: tuple[str, ...]
    depth_by_layer: dict[str, dict[str, Any]]
    candidate_layer_count: int = 0
    resolved_layer_count: int = 0


def _soundg_depth_diagnostic(
    db: Session, layer: ProjectS57LayerRef
) -> dict[str, Any]:
    """Inspect SOUNDG geometry dimension and Z range without reading all rows."""
    diagnostic: dict[str, Any] = {
        "layerId": str(layer.layer_id),
        "sourceCell": layer.source_cell,
        "geometryNdims": None,
        "zMin": None,
        "zMax": None,
        "depthPreserved": None,
        "note": None,
    }
    if (
        db.get_bind().dialect.name != "postgresql"
        or not layer.searchable
        or not layer.geometry_column
        or not layer.source_table
    ):
        return diagnostic
    table = _safe_table(layer.source_table)
    geometry = _quote_identifier(layer.geometry_column)
    _apply_statement_timeout(db)
    try:
        with db.begin_nested():
            row = db.execute(
                text(
                    f"SELECT ST_NDims(w.{geometry}) AS ndims, "
                    f"ST_ZMin(w.{geometry}) AS zmin, "
                    f"ST_ZMax(w.{geometry}) AS zmax "
                    f"FROM {table} AS w "
                    f"WHERE w.{geometry} IS NOT NULL LIMIT 1"
                )
            ).mappings().first()
    except DBAPIError:
        logger.warning("SOUNDG 几何维度诊断失败", exc_info=True)
        diagnostic["note"] = "SOUNDG 几何维度诊断失败，深度保真状态未知。"
        return diagnostic
    if not row:
        diagnostic["note"] = "SOUNDG 图层没有可读取的非空几何。"
        return diagnostic
    try:
        ndims = int(row["ndims"]) if row.get("ndims") is not None else None
    except (TypeError, ValueError):
        ndims = None
    diagnostic["geometryNdims"] = ndims
    diagnostic["zMin"] = float(row["zmin"]) if row.get("zmin") is not None else None
    diagnostic["zMax"] = float(row["zmax"]) if row.get("zmax") is not None else None
    diagnostic["depthPreserved"] = bool(ndims and ndims >= 3)
    diagnostic["note"] = (
        "几何保留 Z 维度；深度单位/符号仍需以源 S-57 为准。"
        if diagnostic["depthPreserved"]
        else "几何为 2D，SOUNDG 深度可能未保留；导出会明确标记，不伪造深度。"
    )
    return diagnostic


def resolve_thematic_layers(
    db: Session, project_id: UUID
) -> ThematicResolution:
    project = resolve_project_s57_layers(db, project_id)
    depth_by_layer: dict[str, dict[str, Any]] = {}
    for layer in project.layers:
        if layer.object_class == "SOUNDG":
            depth_by_layer[str(layer.layer_id)] = _soundg_depth_diagnostic(db, layer)
            # Release each table's AccessShareLock; a large ENC library can
            # have hundreds of SOUNDG layers.
            db.rollback()
    warnings = list(project.warnings)
    if any(
        diagnostic.get("depthPreserved") is False
        for diagnostic in depth_by_layer.values()
    ):
        warnings.append(
            "部分 SOUNDG 图层几何为 2D，深度可能未保留；导出会在 manifest 中标记，"
            "不会用 DEPARE 范围替代测深值。"
        )
    return ThematicResolution(
        layers=project.layers,
        warnings=tuple(warnings),
        depth_by_layer=depth_by_layer,
        candidate_layer_count=project.candidate_layer_count,
        resolved_layer_count=project.resolved_layer_count,
    )


def _fill_layer_counts(
    db: Session,
    layers: tuple[ProjectS57LayerRef, ...],
    batch_size: int = 50,
) -> dict[str, int | None]:
    """Batched COUNT(*) pass with a rollback per batch.

    A large ENC library exposes thousands of geo.* tables. A single
    transaction holding one AccessShareLock per table exhausts PostgreSQL's
    lock table, so counts are grouped (50 tables) and the transaction is
    rolled back after each batch. Failures fall back to per-table counts and
    finally to None ("unknown").
    """
    counts: dict[str, int | None] = {}
    candidates = [
        layer
        for layer in layers
        if layer.searchable
        and layer.source_table
        and layer.geometry_column
        and layer.geometry_type
    ]
    for layer in layers:
        counts[str(layer.layer_id)] = None

    for start in range(0, len(candidates), batch_size):
        batch = candidates[start : start + batch_size]
        selects = []
        for index, layer in enumerate(batch):
            table = _safe_table(layer.source_table)
            selects.append(f"SELECT {index} AS idx, COUNT(*) AS c FROM {table}")
        _apply_statement_timeout(db)
        try:
            with db.begin_nested():
                rows = db.execute(text(" UNION ALL ".join(selects))).all()
                for idx, value in rows:
                    counts[str(batch[int(idx)].layer_id)] = int(value or 0)
        except DBAPIError:
            # One broken/missing table should not erase the whole batch.
            for layer in batch:
                try:
                    with db.begin_nested():
                        value = db.scalar(
                            text(f"SELECT COUNT(*) FROM {_safe_table(layer.source_table)}")
                        )
                        counts[str(layer.layer_id)] = int(value or 0)
                except DBAPIError:
                    counts[str(layer.layer_id)] = None
        db.rollback()
    return counts


def _layer_ref(
    layer: ProjectS57LayerRef, counts: dict[str, int | None] | None = None
) -> dict[str, Any]:
    feature_count = (
        counts.get(str(layer.layer_id), layer.feature_count)
        if counts is not None
        else layer.feature_count
    )
    return {
        "id": str(layer.layer_id),
        "name": layer.layer_name,
        "code": layer.layer_code,
        "datasetCode": layer.dataset_code,
        "datasetName": layer.dataset_name,
        "versionNo": layer.version_no,
        "sourceCell": layer.source_cell,
        "featureCount": feature_count,
        "queryable": layer.queryable,
        "renderable": layer.renderable,
        "available": layer.available and layer.searchable,
        "extractable": bool(
            layer.searchable and layer.geometry_column and layer.geometry_type
        ),
        "geometryType": layer.geometry_type,
        "reason": layer.reason,
    }


def _class_ref(
    rule: ThematicClassRule,
    layers: list[ProjectS57LayerRef],
    counts: dict[str, int | None] | None = None,
) -> dict[str, Any]:
    layer_counts = [
        (
            counts.get(str(layer.layer_id), layer.feature_count)
            if counts is not None
            else layer.feature_count
        )
        for layer in layers
    ]
    return {
        "code": rule.code,
        "nameZh": rule.name_zh,
        "category": rule.category,
        "categoryNameZh": CATEGORY_NAMES[rule.category],
        "description": rule.description,
        "caveats": list(rule.caveats),
        "defaultSelected": rule.default_selected,
        "count": sum(count for count in layer_counts if count is not None),
        "countComplete": all(count is not None for count in layer_counts),
        "layerCount": len(layers),
        "queryable": any(layer.searchable for layer in layers),
        "renderable": any(layer.renderable for layer in layers),
        "extractable": any(
            layer.searchable and layer.geometry_column and layer.geometry_type
            for layer in layers
        ),
        "layers": [_layer_ref(layer, counts) for layer in layers],
    }


def build_thematic_catalog(db: Session, project_id: UUID) -> dict[str, Any]:
    resolution = resolve_thematic_layers(db, project_id)
    counts = _fill_layer_counts(db, resolution.layers)
    by_class: dict[str, list[ProjectS57LayerRef]] = {}
    for layer in resolution.layers:
        by_class.setdefault(layer.object_class, []).append(layer)

    classes: list[dict[str, Any]] = []
    for rule in _DEFINITIONS:
        classes.append(_class_ref(rule, by_class.pop(rule.code, []), counts))
    for code in sorted(by_class):
        classes.append(
            _class_ref(thematic_rule_or_other(code), by_class[code], counts)
        )

    categories: list[dict[str, Any]] = []
    for category in CATEGORY_ORDER:
        category_classes = [
            item for item in classes if item["category"] == category
        ]
        if category == "other" and not category_classes:
            continue
        categories.append(
            {
                "code": category,
                "nameZh": CATEGORY_NAMES[category],
                "classes": category_classes,
            }
        )

    cells: dict[str, dict[str, Any]] = {}
    datasets: dict[str, dict[str, Any]] = {}
    for layer in resolution.layers:
        cell = layer.source_cell or "UNKNOWN"
        cell_entry = cells.setdefault(
            cell,
            {
                "sourceCell": cell,
                "layerCount": 0,
                "featureCount": 0,
                "datasetCodes": set(),
                "objectClasses": set(),
            },
        )
        cell_entry["layerCount"] += 1
        cell_entry["featureCount"] += counts.get(str(layer.layer_id)) or 0
        cell_entry["datasetCodes"].add(layer.dataset_code)
        cell_entry["objectClasses"].add(layer.object_class)
        dataset_entry = datasets.setdefault(
            str(layer.dataset_id),
            {
                "datasetId": str(layer.dataset_id),
                "datasetCode": layer.dataset_code,
                "datasetName": layer.dataset_name,
                "versionNo": layer.version_no,
                "sourceCell": layer.source_cell,
                "layerCount": 0,
                "featureCount": 0,
            },
        )
        dataset_entry["layerCount"] += 1
        dataset_entry["featureCount"] += counts.get(str(layer.layer_id)) or 0

    cell_items = [
        {
            **entry,
            "datasetCodes": sorted(entry["datasetCodes"]),
            "objectClasses": sorted(entry["objectClasses"]),
        }
        for entry in sorted(cells.values(), key=lambda item: item["sourceCell"])
    ]
    dataset_items = sorted(datasets.values(), key=lambda item: item["datasetCode"])

    soundg_diagnostics = [
        diagnostic
        for diagnostic in resolution.depth_by_layer.values()
        if diagnostic.get("sourceCell")
    ]
    known_depth_states = [
        diagnostic.get("depthPreserved")
        for diagnostic in soundg_diagnostics
        if diagnostic.get("depthPreserved") is not None
    ]
    if any(state is False for state in known_depth_states):
        depth_preserved: bool | None = False
    elif known_depth_states and all(state is True for state in known_depth_states):
        depth_preserved = True
    else:
        depth_preserved = None
    feature_count = sum(item["count"] for item in classes)
    return {
        "categories": categories,
        "classes": classes,
        "totalLayerCount": len(resolution.layers),
        "extractableLayerCount": sum(
            1
            for layer in resolution.layers
            if layer.searchable and layer.geometry_column and layer.geometry_type
        ),
        "featureCount": feature_count,
        "countComplete": all(item["countComplete"] for item in classes),
        "candidateLayerCount": resolution.candidate_layer_count,
        "resolvedLayerCount": resolution.resolved_layer_count,
        "cells": cell_items,
        "datasets": dataset_items,
        "soundgDepth": {
            "layers": soundg_diagnostics,
            "depthPreserved": depth_preserved,
            "note": (
                "SOUNDG feature 数不是单个测深点数量；深度可能在几何 Z 或 DEPTH 属性。"
                "单位/符号/垂直基准需以源 S-57 为准。"
            ),
        },
        "warnings": list(resolution.warnings),
        "semantics": [],
    }
