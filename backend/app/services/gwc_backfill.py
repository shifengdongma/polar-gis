"""GWC EPSG:3413 tile-cache backfill.

Shared between the FastAPI lifespan startup thread and the admin endpoint
``POST /api/v1/admin/gwc/backfill``. The worker process runs its own script
(``app.worker.main``) and never executes this, so there is no dual-process race.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import Dataset, DatasetType, DatasetVersion, Layer, LayerStatus
from app.services.geoserver import GeoServerClient

logger = logging.getLogger(__name__)

GWC_3413_GRIDSET = "EPSG:3413"
GWC_3413_CRS = "EPSG:3413"
GWC_3413_EXTENT = [-4194304.0, -4194304.0, 4194304.0, 4194304.0]
GWC_LAYER_GRIDSETS = ["EPSG:3857", "EPSG:4326", "EPSG:3413"]
GWC_LAYER_MIME_FORMATS = ["image/png"]


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
            Dataset.deleted_at.is_(None),
        )
    ).all()

    updated = 0
    for layer in layers:
        layer_name = layer.geoserver_layer_name or layer.code
        qualified = f"{layer.geoserver_workspace or settings.geoserver_workspace}:{layer_name}"
        try:
            response = geoserver._request(
                "GET",
                f"gwc/layers/{qualified}.json",
                allowed_statuses={200, 404},
            )
        except Exception as exc:
            logger.warning("检查图层 %s 的 GWC 配置失败: %s", qualified, exc)
            continue
        if response.status_code == 404:
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
        try:
            data = response.json()
        except ValueError:
            data = {}
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
