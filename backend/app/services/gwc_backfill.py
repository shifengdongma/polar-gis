"""GWC EPSG:3413 tile-cache backfill.

Shared between the FastAPI lifespan startup thread and the admin endpoint
``POST /api/v1/admin/gwc/backfill``. The worker process runs its own script
(``app.worker.main``) and never executes this, so there is no dual-process race.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import BaseMap, Dataset, DatasetType, DatasetVersion, Layer, LayerStatus
from app.services.geoserver import GeoServerClient
from app.services.wmts_tiles import (
    GWC_3413_CRS,
    GWC_3413_EXTENT,
    GWC_3413_GRIDSET,
    GWC_LAYER_GRIDSETS,
    GWC_LAYER_MIME_FORMATS,
    OVERVIEW_BASEMAP_NAMES,
    OVERVIEW_LAYER_GROUP,
    overview_wmts_tile_template,
)

logger = logging.getLogger(__name__)


def ensure_gwc_3413_backfill(
    db: Session,
    geoserver: GeoServerClient | None = None,
    settings: Settings | None = None,
) -> dict:
    """Idempotently enable EPSG:3413 GWC caching for all available S-57 layers.

    1. PUT the EPSG:3413 gridset (idempotent, 22 zoom levels).
    2. Find every available S-57 layer with a GeoServer layer name.
    3. GET each GWC layer config; only PUT when "EPSG:3413" is missing from
       its gridSubsets (GET-then-PUT avoids flooding GeoServer with PUTs).

    Returns a summary dict like ``{"checked": N, "updated": N, "skipped": False}``.
    Controlled by ``GWC_3413_BACKFILL`` (default enabled; ``=0``/``false`` disables).
    """
    settings = settings or get_settings()
    if not settings.gwc_3413_backfill:
        logger.info("GWC_3413_BACKFILL 已禁用，跳过 EPSG:3413 回填")
        return {"checked": 0, "updated": 0, "skipped": True}

    geoserver = geoserver or GeoServerClient(settings)
    geoserver.ensure_gridset(GWC_3413_GRIDSET, GWC_3413_CRS, GWC_3413_EXTENT)

    layers = db.scalars(
        select(Layer)
        .join(DatasetVersion, Layer.dataset_version_id == DatasetVersion.id)
        .join(Dataset, DatasetVersion.dataset_id == Dataset.id)
        .where(
            Layer.status == LayerStatus.AVAILABLE.value,
            Layer.geoserver_layer_name.is_not(None),
            Layer.geoserver_layer_name != "",
            Layer.deleted_at.is_(None),
            Dataset.data_type == DatasetType.S57.value,
            Dataset.current_version_id == Layer.dataset_version_id,
            Dataset.deleted_at.is_(None),
        )
    ).all()

    updated = 0
    for layer in layers:
        layer_name = layer.geoserver_layer_name or layer.code
        qualified = f"{layer.geoserver_workspace or settings.geoserver_workspace}:{layer_name}"
        try:
            data = geoserver.get_gwc_layer(layer_name)
        except Exception as exc:
            logger.warning("检查图层 %s 的 GWC 配置失败: %s", qualified, exc)
            continue
        if data is None:
            # Layer not configured in GWC at all — full configuration.
            try:
                geoserver.ensure_gwc_layer(
                    layer_name,
                    gridsets=GWC_LAYER_GRIDSETS,
                    mime_formats=GWC_LAYER_MIME_FORMATS,
                )
            except Exception as exc:
                logger.warning("为图层 %s 启用 GWC 缓存失败: %s", qualified, exc)
                continue
            updated += 1
            continue
        grid_subsets = (data.get("GeoServerLayer") or {}).get("gridSubsets") or []
        grid_names = {gs.get("gridSetName") for gs in grid_subsets}
        if GWC_3413_GRIDSET not in grid_names:
            try:
                geoserver.ensure_gwc_layer(
                    layer_name,
                    gridsets=GWC_LAYER_GRIDSETS,
                    mime_formats=GWC_LAYER_MIME_FORMATS,
                )
            except Exception as exc:
                logger.warning("为图层 %s 补充 EPSG:3413 缓存配置失败: %s", qualified, exc)
                continue
            updated += 1
    return {"checked": len(layers), "updated": updated, "skipped": False}


def ensure_overview_basemap_config(
    db: Session,
    geoserver: GeoServerClient | None = None,
    settings: Settings | None = None,
) -> dict:
    """Repair the overview basemap path for existing deployments.

    1. Add EPSG:3413 to the overview layer group's GWC gridSubsets when the
       group already has a GWC config (the polar WMTS endpoint otherwise
       rejects tiles with "Unable to match requested TILEMATRIXSET").
    2. Rewrite legacy GetCapabilities ``url_template`` values to direct GetTile
       templates. The instance-wide capabilities document is ~729 MB on a
       ~5.8k-layer workspace, so the frontend must not request it.

    Idempotent; failures are logged and never abort startup.
    """
    settings = settings or get_settings()
    geoserver = geoserver or GeoServerClient(settings)

    group_status = "missing"
    try:
        data = geoserver.get_gwc_layer(OVERVIEW_LAYER_GROUP)
        if data is not None:
            grid_subsets = (data.get("GeoServerLayer") or {}).get("gridSubsets") or []
            grid_names = {gs.get("gridSetName") for gs in grid_subsets}
            if set(GWC_LAYER_GRIDSETS).issubset(grid_names):
                group_status = "unchanged"
            else:
                geoserver.ensure_gridset(GWC_3413_GRIDSET, GWC_3413_CRS, GWC_3413_EXTENT)
                geoserver.ensure_gwc_layer(
                    OVERVIEW_LAYER_GROUP,
                    gridsets=GWC_LAYER_GRIDSETS,
                    mime_formats=GWC_LAYER_MIME_FORMATS,
                )
                group_status = "updated"
    except Exception as exc:
        logger.warning("检查概览底图 GWC 配置失败: %s", exc)
        group_status = "failed"

    templates_updated = 0
    names = set(OVERVIEW_BASEMAP_NAMES.values())
    base_maps = db.scalars(
        select(BaseMap).where(
            BaseMap.name.in_(names),
            BaseMap.deleted_at.is_(None),
        )
    ).all()
    for base_map in base_maps:
        # Only migrate the system-generated legacy value; never clobber an
        # administrator's custom URL for these rows.
        if "getcapabilities" not in base_map.url_template.lower():
            continue
        try:
            base_map.url_template = overview_wmts_tile_template(
                settings.geoserver_public_url,
                settings.geoserver_workspace,
                base_map.crs,
            )
        except ValueError:
            continue
        base_map.map_type = "WMTS"
        templates_updated += 1
    if templates_updated:
        db.commit()

    return {
        "group": group_status,
        "templatesUpdated": templates_updated,
    }
