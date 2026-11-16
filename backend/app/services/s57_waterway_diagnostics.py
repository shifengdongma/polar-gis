"""Read-only completeness diagnostics for the S-57 waterway thematic.

The service answers a narrow question: which ENC cells/classes are actually
associated with this project, what can be queried/rendered, and which macro
regions relevant to the Northeast Passage / Northern Sea Route are missing.

It does not join traffic-separation fragments into a route, does not invent
coverage, and never exposes SQL, table names or credentials to the client.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.s57_project_layers import (
    ProjectS57LayerRef,
    resolve_project_s57_layers,
)
from app.services.s57_waterway_catalog import WATERWAY_CLASS_RULES
from app.services.s57_waterways import (
    _apply_statement_timeout,
    _quote_identifier,
    _safe_table,
    build_catalog,
    resolve_waterway_layers,
)

CHECKED_AT = "2026-11-16"

# Approximate research corridors only. These are not legal boundaries and not
# navigation routes; they exist solely to compare project ENC coverage.
REGIONS: tuple[dict[str, Any], ...] = (
    {
        "code": "norwegian_barents",
        "nameZh": "挪威海/巴伦支海入口",
        "boxes": ((0.0, 55.0, 60.0, 75.0),),
    },
    {
        "code": "kara",
        "nameZh": "喀拉海",
        "boxes": ((55.0, 65.0, 105.0, 82.0),),
    },
    {
        "code": "laptev",
        "nameZh": "拉普捷夫海",
        "boxes": ((100.0, 68.0, 145.0, 82.0),),
    },
    {
        "code": "east_siberian",
        "nameZh": "东西伯利亚海",
        "boxes": ((140.0, 66.0, 180.0, 80.0),),
    },
    {
        "code": "chukchi_bering",
        "nameZh": "楚科奇海/白令海峡",
        "boxes": ((170.0, 62.0, 180.0, 75.0), (-180.0, 62.0, -160.0, 75.0)),
    },
)

NEP_REGION_CODES = frozenset(
    {"kara", "laptev", "east_siberian", "chukchi_bering"}
)

REFERENCES: tuple[dict[str, str], ...] = (
    {
        "title": "USNIC Arctic Sea Routes",
        "url": "https://usicecenter.gov/Catalog/ArcticSeaRoutes",
        "scope": (
            "NSR 冰情/海路图产品覆盖约 40°E–160°W、70°N 以北；这是产品范围，"
            "不是法定航道边界或唯一推荐航线。"
        ),
        "checkedAt": CHECKED_AT,
    },
    {
        "title": "PAME Arctic Marine Shipping Assessment (AMSA)",
        "url": (
            "https://www.pame.is/ourwork/arctic-shipping/"
            "arctic-marine-shipping-assessment/"
        ),
        "scope": (
            "北极航运战略评估，讨论北方海航道、西北航道等；该页面不定义"
            "东北航道/北方海航道的法定边界。"
        ),
        "checkedAt": CHECKED_AT,
    },
    {
        "title": "Arctic Portal — Arctic Sea Routes / Northeast Passage and EEZs",
        "url": (
            "https://arcticportal.org/downloads/maps/maps-shipping/"
            "2797-arctic-sea-routes-northeast-passage-and-eezs"
        ),
        "scope": (
            "展示主要北极海路与专属经济区的参考地图；不是航海许可或"
            "法定边界。"
        ),
        "checkedAt": CHECKED_AT,
    },
    {
        "title": "IHO S-57 standards and object catalogue",
        "url": "https://iho.int/standards-and-specifications",
        "scope": (
            "S-57 ENC 产品规范与对象目录（S-57 仍在使用，S-101 为后续标准）；"
            "DWRTCL/DWRTPT/RCRTCL/RCTLPT 分别为深水航道中心线/部分、"
            "推荐航线中心线、推荐通航车道部分。"
        ),
        "checkedAt": CHECKED_AT,
    },
    {
        "title": "GDAL S-57 driver",
        "url": "https://gdal.org/en/stable/drivers/vector/s57.html",
        "scope": (
            "SOUNDG 默认为 3D 点几何；SPLIT_MULTIPOINT 与 ADD_SOUNDG_DEPTH "
            "默认关闭，深度单位/符号需以源数据为准。"
        ),
        "checkedAt": CHECKED_AT,
    },
)


def _bbox_intersects(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    return not (
        a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3]
    )


def _region_hit(
    bbox: tuple[float, float, float, float] | None,
    boxes: tuple[tuple[float, float, float, float], ...],
) -> bool:
    if not bbox:
        return False
    # A cell bbox crossing the antimeridian is normalised into two boxes.
    cell_boxes = (
        ((bbox[0], bbox[1], 180.0, bbox[3]), (-180.0, bbox[1], bbox[2], bbox[3]))
        if bbox[0] > bbox[2]
        else (bbox,)
    )
    return any(_bbox_intersects(cell, box) for cell in cell_boxes for box in boxes)


def _coverage_bbox_for_cell(
    db: Session,
    layers: list[ProjectS57LayerRef],
    source_cell: str,
) -> tuple[tuple[float, float, float, float] | None, str, bool]:
    """Prefer M_COVR coverage polygons; fall back to layer metadata extents."""
    m_covr_layers = [
        layer
        for layer in layers
        if layer.source_cell == source_cell
        and layer.object_class == "M_COVR"
        and layer.queryable
        and layer.available
        and layer.source_table
        and layer.geometry_column
    ]
    if m_covr_layers and db.get_bind().dialect.name == "postgresql":
        layer = m_covr_layers[0]
        table = _safe_table(layer.source_table)
        geometry = _quote_identifier(layer.geometry_column)
        catcov_filter = ""
        if "catcov" in layer.fields:
            catcov_filter = (
                f" WHERE CAST(w.{_quote_identifier('catcov')} AS TEXT) "
                "IN ('1', '1.0')"
            )
        sql = (
            "SELECT ST_XMin(e) AS xmin, ST_YMin(e) AS ymin, "
            "ST_XMax(e) AS xmax, ST_YMax(e) AS ymax "
            "FROM (SELECT ST_Extent(ST_Transform(w."
            f"{geometry}, 4326)) AS e FROM {table} AS w{catcov_filter}) AS q"
        )
        _apply_statement_timeout(db)
        try:
            with db.begin_nested():
                row = db.execute(text(sql)).mappings().first()
        except DBAPIError:
            row = None
        if row and all(row.get(key) is not None for key in ("xmin", "ymin", "xmax", "ymax")):
            return (
                (
                    float(row["xmin"]),
                    float(row["ymin"]),
                    float(row["xmax"]),
                    float(row["ymax"]),
                ),
                "m_covr",
                True,
            )

    extents = [
        layer.extent
        for layer in layers
        if layer.source_cell == source_cell and layer.extent is not None
    ]
    if extents:
        return (
            (
                min(item[0] for item in extents),
                min(item[1] for item in extents),
                max(item[2] for item in extents),
                max(item[3] for item in extents),
            ),
            "layer_extent",
            False,
        )
    return None, "unknown", False


def _cell_status_reason(
    cell_layers: list[ProjectS57LayerRef],
    waterway_layers: list[Any],
) -> list[str]:
    reasons: list[str] = []
    if not waterway_layers:
        reasons.append("该 Cell 未关联航道专题图层")
    for layer in waterway_layers:
        if layer.reason:
            reasons.append(f"{layer.object_class}: {layer.reason}")
    for layer in cell_layers:
        if not layer.available and layer.reason:
            reasons.append(f"{layer.object_class}: {layer.reason}")
    return sorted(set(reasons))


def build_waterway_diagnostics(db: Session, project_id: UUID) -> dict[str, Any]:
    settings = get_settings()
    waterway_resolution = resolve_waterway_layers(db, project_id)
    project_resolution = resolve_project_s57_layers(db, project_id)
    warnings = list(waterway_resolution.warnings) + list(project_resolution.warnings)

    all_layers = list(project_resolution.layers)
    waterway_layers = list(waterway_resolution.layers)
    waterway_by_cell: dict[str, list[Any]] = {}
    for layer in waterway_layers:
        if layer.source_cell:
            waterway_by_cell.setdefault(layer.source_cell, []).append(layer)

    cell_names = sorted(
        {layer.source_cell for layer in all_layers if layer.source_cell}
    )
    cells: list[dict[str, Any]] = []
    coverage_by_cell: dict[str, tuple[float, float, float, float] | None] = {}
    for cell in cell_names:
        cell_layers = [layer for layer in all_layers if layer.source_cell == cell]
        cell_waterway_layers = waterway_by_cell.get(cell, [])
        bbox, coverage_source, coverage_verified = _coverage_bbox_for_cell(
            db, all_layers, cell
        )
        # Read-only diagnostic; release the M_COVR table lock before the next
        # cell so large projects do not exhaust max_locks_per_transaction.
        db.rollback()
        coverage_by_cell[cell] = bbox
        feature_count = sum(
            layer.feature_count for layer in cell_layers if layer.feature_count is not None
        )
        waterway_feature_count = sum(
            layer.feature_count
            for layer in cell_waterway_layers
            if layer.feature_count is not None
        )
        cells.append(
            {
                "sourceCell": cell,
                "datasetCodes": sorted({layer.dataset_code for layer in cell_layers}),
                "datasetNames": sorted({layer.dataset_name for layer in cell_layers}),
                "versionNos": sorted({layer.version_no for layer in cell_layers}),
                "layerCount": len(cell_layers),
                "waterwayLayerCount": len(cell_waterway_layers),
                "searchableLayerCount": sum(
                    1 for layer in cell_waterway_layers if layer.searchable
                ),
                "renderableLayerCount": sum(
                    1 for layer in cell_waterway_layers if layer.renderable
                ),
                "featureCount": feature_count,
                "waterwayFeatureCount": waterway_feature_count,
                "countComplete": all(
                    layer.feature_count is not None for layer in cell_layers
                ),
                "objectClasses": sorted({layer.object_class for layer in cell_layers}),
                "waterwayClasses": sorted(
                    {layer.object_class for layer in cell_waterway_layers}
                ),
                "bbox": list(bbox) if bbox else None,
                "coverageSource": coverage_source,
                "coverageVerified": coverage_verified,
                "reasons": _cell_status_reason(cell_layers, cell_waterway_layers),
            }
        )

    if any(coverage_by_cell.get(cell) is None for cell in cell_names):
        warnings.append(
            "部分 Cell 缺少可用覆盖范围（M_COVR/图层 extent 均不可用），区域对照可能不完整"
        )

    regions: list[dict[str, Any]] = []
    for region in REGIONS:
        intersecting = [
            cell
            for cell in cell_names
            if _region_hit(coverage_by_cell.get(cell), region["boxes"])
        ]
        region_waterway_layers = [
            layer
            for cell in intersecting
            for layer in waterway_by_cell.get(cell, [])
        ]
        non_auxiliary = [
            layer
            for layer in region_waterway_layers
            if not WATERWAY_CLASS_RULES[layer.object_class].auxiliary
        ]
        non_auxiliary_with_data = [
            layer
            for layer in non_auxiliary
            if layer.feature_count is None or layer.feature_count > 0
        ]
        auxiliary = [
            layer
            for layer in region_waterway_layers
            if WATERWAY_CLASS_RULES[layer.object_class].auxiliary
        ]
        if not intersecting:
            status = "no_enc_imported"
        elif non_auxiliary_with_data:
            status = "imported_enc_coverage"
        elif auxiliary:
            status = "only_basemap_or_auxiliary"
        else:
            status = "no_waterway_objects"
        regions.append(
            {
                "code": region["code"],
                "nameZh": region["nameZh"],
                "approximateBbox": [list(box) for box in region["boxes"]],
                "status": status,
                "cells": intersecting,
                "waterwayClasses": sorted(
                    {layer.object_class for layer in region_waterway_layers}
                ),
                "featureCount": sum(
                    layer.feature_count
                    for layer in region_waterway_layers
                    if layer.feature_count is not None
                ),
                "countComplete": all(
                    layer.feature_count is not None
                    for layer in region_waterway_layers
                ),
                "note": (
                    "按 Cell/M_COVR/图层外围范围近似判断，不代表区域完整覆盖；"
                    "研究对照范围，不是法定边界。"
                ),
            }
        )

    missing_regions = [
        {
            "code": region["code"],
            "nameZh": region["nameZh"],
            "status": region["status"],
        }
        for region in regions
        if region["code"] in NEP_REGION_CODES
        and region["status"] != "imported_enc_coverage"
    ]
    northeast_passage = {
        "hasGap": bool(missing_regions),
        "missingRegions": missing_regions,
        "summary": (
            "当前项目未检测到以下东北航道/北方海航道研究区域的航道 ENC 覆盖："
            + "、".join(item["nameZh"] for item in missing_regions)
            + "。如已有合法授权 ENC，请通过批量导入并关联项目后重新诊断。"
            if missing_regions
            else "当前项目在对照区域均检测到已关联的航道 ENC；仍为范围近似，不代表完整测深或官方航线。"
        ),
        "definitions": {
            "northeastPassage": "东北航道（NEP）：连接巴伦支海与白令海峡的宏观地理概念。",
            "northernSeaRoute": (
                "北方海航道（NSR）：俄罗斯北极水域的航运管理概念，与 NEP 相关但不完全相同。"
            ),
            "coverageCaveat": (
                "USNIC NSR 产品覆盖约 40°E–160°W、70°N 以北只是产品范围，"
                "不是法定边界或唯一推荐航线。"
            ),
        },
    }

    catalog = build_catalog(waterway_resolution)
    total_features = sum(
        layer.feature_count
        for layer in waterway_layers
        if layer.feature_count is not None
    )
    return {
        "projectId": str(project_id),
        "generatedAt": datetime.now(UTC).isoformat(),
        "totals": {
            "linkedCellCount": len(cell_names),
            "waterwayLayerCount": len(waterway_layers),
            "searchableLayerCount": sum(
                1 for layer in waterway_layers if layer.searchable
            ),
            "renderableLayerCount": sum(
                1 for layer in waterway_layers if layer.renderable
            ),
            "featureCount": total_features,
            "countComplete": all(
                layer.feature_count is not None for layer in waterway_layers
            ),
            "candidateLayerCount": project_resolution.candidate_layer_count,
            "resolvedLayerCount": project_resolution.resolved_layer_count,
            "catalogTruncated": waterway_resolution.truncated,
            "layerWarningThreshold": settings.s57_waterway_query_warning_layers,
        },
        "cells": cells,
        "classes": catalog["classes"],
        "regions": regions,
        "northeastPassage": northeast_passage,
        "references": [dict(item) for item in REFERENCES],
        "notes": [
            "仅统计当前项目已关联的当前版本 S-57 图层；未关联的数据集不会出现在此结果。",
            "覆盖范围优先使用 M_COVR（CATCOV=1）的外围 bbox，否则使用图层 extent；"
            "矩形范围不等于整片海域都有可靠测深。",
            "交通分隔制 ≠ 推荐航路；局部 S-57 要素 ≠ 完整规划航线。",
            "东北航道（NEP）与北方海航道（NSR）相关但不完全相同。",
        ],
        "warnings": warnings,
        "checkedAt": CHECKED_AT,
    }
