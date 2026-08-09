"""Idempotent S-57 SLD style sync with scale rules and GWC cache invalidation.

Shared between the S-57 import path (``importer.ImportProcessor._apply_s57_style``)
and the admin endpoint ``POST /api/v1/admin/styles/refresh-s57`` (deployment-time
refresh of already-imported layers from single-rule SLDs to scale rules).

Every generated SLD is hashed (sha256) and stored under
``layer.metadata_json["s57"]["sldHash"]``.  Only when the hash actually changes
is the style re-published to GeoServer and the layer's GWC tile cache
truncated (masstruncate is idempotent and tolerates 404 for uncached layers),
which keeps re-imports and refresh runs cheap.
"""

import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    Dataset,
    DatasetType,
    DatasetVersion,
    Layer,
    LayerStatus,
    Style,
)
from app.services.geoserver import GeoServerClient
from app.services.s57_layer_catalog import classify_s57_layer
from app.services.s57_styles import preset_for_object_class

logger = logging.getLogger(__name__)


def sync_s57_layer_style(
    db: Session,
    layer: Layer,
    geoserver: GeoServerClient,
) -> dict:
    """Publish (idempotently) the scale-aware preset SLD for one S-57 layer.

    - Computes the SLD for the layer's style preset with the min scale
      denominator from the classification output (metadata
      ``s57.minScaleDenominator``, falling back to a fresh
      ``classify_s57_layer`` call).
    - Compares its sha256 against ``metadata_json["s57"]["sldHash"]``.
    - Only when the SLD actually changed: PUT to GeoServer, truncate the GWC
      tile cache for the layer (best-effort, never interrupts import), and
      persist the new hash plus mapping metadata.
    - Layers without a style preset are marked ``s57StyleStatus=unmapped`` and
      left untouched.

    Returns ``{"changed": bool, "style_code": str | None}``.
    """
    metadata = layer.metadata_json or {}
    source_layer = str(metadata.get("sourceLayer", ""))
    preset = preset_for_object_class(source_layer)
    if preset is None:
        s57_meta = dict(metadata.get("s57") or {})
        s57_meta["styleMapped"] = False
        layer.metadata_json = {
            **metadata,
            "s57StyleStatus": "unmapped",
            "s57": s57_meta,
        }
        return {"changed": False, "style_code": None}

    s57_meta = dict(metadata.get("s57") or {})
    min_scale = s57_meta.get("minScaleDenominator")
    if min_scale is None:
        rule = classify_s57_layer(source_layer, layer.geometry_type, True)
        min_scale = rule.min_scale_denominator

    sld = preset.render_sld(min_scale_denominator=min_scale)
    sld_hash = hashlib.sha256(sld.encode("utf-8")).hexdigest()

    if s57_meta.get("sldHash") == sld_hash:
        return {"changed": False, "style_code": preset.code}

    style = db.scalar(select(Style).where(Style.code == preset.code))
    if style is None:
        style = Style(
            code=preset.code,
            name=preset.name,
            geoserver_style_name=preset.code,
            status="published",
        )
        db.add(style)
        db.flush()

    geoserver.publish_style(preset.code, sld)
    geoserver.set_default_style(layer.geoserver_layer_name or layer.code, preset.code)
    try:
        geoserver.truncate_layer_cache(layer.geoserver_layer_name or layer.code)
    except Exception as exc:
        logger.warning("清空图层 %s 的 GWC 瓦片缓存失败: %s", layer.code, exc)

    s57_meta["styleMapped"] = True
    s57_meta["sldHash"] = sld_hash
    layer.metadata_json = {
        **metadata,
        "recommendedStyleCode": preset.code,
        "recommendedStyleId": str(style.id),
        "s57StyleStatus": "mapped",
        "s57": s57_meta,
    }
    return {"changed": True, "style_code": preset.code}


def refresh_s57_layer_styles(
    db: Session,
    geoserver: GeoServerClient | None = None,
    settings: Settings | None = None,
) -> dict:
    """Idempotently re-apply scale-aware S-57 SLDs to all available S-57 layers.

    Only layers whose SLD hash differs from the previously deployed one are
    re-published and have their GWC tile cache truncated.  Intended for
    deployment-time refresh of already-imported layers.

    Returns ``{"checked": N, "updated": N, "failed": N}``.
    """
    settings = settings or get_settings()
    geoserver = geoserver or GeoServerClient(settings)
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
    failed = 0
    for layer in layers:
        try:
            result = sync_s57_layer_style(db, layer, geoserver)
            if result["changed"]:
                updated += 1
        except Exception as exc:
            logger.warning("刷新图层 %s 的 S-57 样式失败: %s", layer.code, exc)
            failed += 1
    db.commit()
    return {"checked": len(layers), "updated": updated, "failed": failed}
