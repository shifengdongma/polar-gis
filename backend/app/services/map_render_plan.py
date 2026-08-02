"""Pure-function render plan service for smart-mode bundle grouping.

Groups logical S-57 layers into semantic render bundles (multi-layer WMS)
to reduce independent HTTP tile requests. No DB, HTTP, or GeoServer dependencies.

Consumes ``get_render_bucket()`` and ``get_bucket_z_index()`` from
``s57_layer_catalog.py`` — the single source of truth for bucket assignment.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Final

from app.services.s57_layer_catalog import get_bucket_z_index, get_render_bucket

# ── Constants ───────────────────────────────────────────────────────────────

MAX_LAYERS_PER_BUNDLE: Final[int] = 20
MAX_BUNDLE_URL_LENGTH: Final[int] = 2000

# Bundle display metadata and sort order (render-plan concerns, not in catalog).
_BUCKET_NAMES: Final[dict[str, str]] = {
    "area_fill": "面域填充",
    "line_structure": "线状结构",
    "hazard_detail": "危险物与水深",
    "navigation_aid": "助航标志",
    "optional_other": "其他可选",
}

_BUCKET_SORT_ORDER: Final[dict[str, int]] = {
    "area_fill": 1,
    "line_structure": 2,
    "hazard_detail": 3,
    "navigation_aid": 4,
    "optional_other": 7,
}


# ── Public data classes ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BundleBucket:
    """A semantic group that maps to one multi-layer WMS request."""

    bucket_id: str
    bucket_name_zh: str
    z_index: int
    sort_order: int


@dataclass(frozen=True, slots=True)
class LayerRenderInput:
    """Minimal layer metadata needed to compute a render bundle assignment."""

    layer_id: str
    geoserver_layer_name: str  # qualified: "workspace:layer_name"
    style_name: str  # qualified: "workspace:style_name"
    object_class: str
    display_category: str
    display_priority: int
    opacity: float = 1.0
    extent: tuple[float, ...] | None = None
    min_zoom: int | None = None
    max_zoom: int | None = None
    render_standalone: bool = False


@dataclass(frozen=True, slots=True)
class BundleConfig:
    """One multi-layer WMS bundle ready for TileWMS creation."""

    bundle_id: str
    bucket: str
    layer_ids: list[str] = field(default_factory=list)
    layer_names: list[str] = field(default_factory=list)
    styles: list[str] = field(default_factory=list)
    z_index: int = 10
    opacity: float = 1.0
    extent: list[float] | None = None
    min_zoom: int | None = None
    max_zoom: int | None = None
    transport: str = "wms_multi"
    service_url: str = "/geoserver/polar_gis/wms"
    cache_key: str = ""


@dataclass(frozen=True, slots=True)
class StandaloneConfig:
    """A single layer that cannot be bundled (custom opacity, forced, etc.)."""

    layer_id: str
    layer_name: str
    style: str
    z_index: int
    opacity: float
    reason: str  # "custom_opacity", "render_standalone"


@dataclass(frozen=True, slots=True)
class RenderPlanSummary:
    logical_layer_count: int = 0
    bundle_count: int = 0
    standalone_count: int = 0
    estimated_request_reduction_ratio: float = 0.0


# ── Bucket assignment ───────────────────────────────────────────────────────


def _make_bucket(bucket_id: str) -> BundleBucket:
    """Build a BundleBucket from a bucket_id using catalog z-index."""
    return BundleBucket(
        bucket_id=bucket_id,
        bucket_name_zh=_BUCKET_NAMES.get(bucket_id, bucket_id),
        z_index=get_bucket_z_index(bucket_id),
        sort_order=_BUCKET_SORT_ORDER.get(bucket_id, 99),
    )


def get_bucket_for_layer(
    display_category: str,
    object_class: str,
) -> BundleBucket | None:
    """Map a layer to its render bucket (delegates to catalog).

    Returns ``None`` for non-spatial layers (excluded from bundles).
    Unknown categories fall back to ``optional_other``.
    """
    bucket_id = get_render_bucket(display_category, object_class)
    if bucket_id is None:
        return None
    return _make_bucket(bucket_id)


# ── Bundle ID and cache key ─────────────────────────────────────────────────


def compute_bundle_id(
    bucket: str,
    layer_names: list[str],
    projection: str,
) -> str:
    """Deterministic bundle ID: ``bucket:hash8``."""
    stable = hashlib.sha256(
        ",".join(sorted(layer_names)).encode()
        + b"|"
        + projection.encode()
        + b"|"
        + bucket.encode()
    ).hexdigest()[:8]
    return f"{bucket}:{stable}"


def bundle_cache_key(
    bucket: str,
    layer_names: list[str],
    projection: str,
) -> str:
    """Deterministic cache key for a bundle (order-independent on layers)."""
    return hashlib.sha256(
        ",".join(sorted(layer_names)).encode()
        + b"|"
        + projection.encode()
        + b"|"
        + bucket.encode()
    ).hexdigest()


# ── Core bundle builder ─────────────────────────────────────────────────────


def build_bundles(
    layers: list[LayerRenderInput],
    profile: str,
    projection: str,
    data_version_hash: str = "",
) -> tuple[list[BundleConfig], list[StandaloneConfig]]:
    """Group logical layers into render bundles + standalone layers.

    Args:
        layers: Logical layers to group.
        profile: Load profile (e.g. ``core_chart``).
        projection: Current CRS (e.g. ``EPSG:3857``).
        data_version_hash: Hash of active data versions for cache invalidation.

    Returns:
        ``(bundles, standalones)`` sorted by bucket sort_order.
    """
    if not layers:
        return [], []

    # 1. Separate standalone layers
    standalone_layers: list[LayerRenderInput] = []
    bundleable: list[LayerRenderInput] = []

    for layer in layers:
        if layer.render_standalone:
            standalone_layers.append(layer)
        elif layer.opacity != 1.0:
            standalone_layers.append(layer)
        else:
            bundleable.append(layer)

    # 2. Group by bucket (delegates to catalog)
    bucket_groups: dict[str, list[LayerRenderInput]] = {}
    for layer in bundleable:
        bucket = get_bucket_for_layer(layer.display_category, layer.object_class)
        if bucket is None:
            # non_spatial → skip entirely
            continue
        bucket_groups.setdefault(bucket.bucket_id, []).append(layer)

    # 3. Build BundleConfig for each bucket
    bundles: list[BundleConfig] = []
    for bucket_id, group in bucket_groups.items():
        # Sort within bucket: display_priority ASC → object_class ASC → layer_id ASC
        group.sort(key=lambda ly: (ly.display_priority, ly.object_class, ly.layer_id))

        bucket_meta = _make_bucket(bucket_id)

        # Split if exceeding max layers per bundle
        for i in range(0, len(group), MAX_LAYERS_PER_BUNDLE):
            chunk = group[i : i + MAX_LAYERS_PER_BUNDLE]
            layer_names = [ly.geoserver_layer_name for ly in chunk]
            cache_key_raw = bundle_cache_key(bucket_id, layer_names, projection)
            # Mix in the data version hash for cache invalidation
            if data_version_hash:
                cache_key_raw = hashlib.sha256(
                    (cache_key_raw + data_version_hash).encode()
                ).hexdigest()

            bundles.append(
                BundleConfig(
                    bundle_id=compute_bundle_id(bucket_id, layer_names, projection),
                    bucket=bucket_id,
                    layer_ids=[ly.layer_id for ly in chunk],
                    layer_names=layer_names,
                    styles=[ly.style_name for ly in chunk],
                    z_index=bucket_meta.z_index,
                    opacity=1.0,
                    extent=_union_extents([ly.extent for ly in chunk if ly.extent]),
                    min_zoom=_min_zoom([ly.min_zoom for ly in chunk]),
                    max_zoom=_max_zoom([ly.max_zoom for ly in chunk]),
                    cache_key=cache_key_raw,
                )
            )

    # 4. Build StandaloneConfig
    standalones: list[StandaloneConfig] = []
    for layer in standalone_layers:
        bucket = get_bucket_for_layer(layer.display_category, layer.object_class)
        bucket_meta = bucket if bucket else _make_bucket("optional_other")
        reason = "render_standalone" if layer.render_standalone else "custom_opacity"
        standalones.append(
            StandaloneConfig(
                layer_id=layer.layer_id,
                layer_name=layer.geoserver_layer_name,
                style=layer.style_name,
                z_index=bucket_meta.z_index,
                opacity=layer.opacity,
                reason=reason,
            )
        )

    # 5. Sort bundles by bucket sort_order
    bundles.sort(key=lambda b: _BUCKET_SORT_ORDER.get(b.bucket, 99))

    return bundles, standalones


# ── Internal helpers ────────────────────────────────────────────────────────


def _union_extents(extents: list[tuple[float, ...] | None]) -> list[float] | None:
    """Union multiple extents into a single bounding box, or None if all empty."""
    valid = [e for e in extents if e is not None and len(e) == 4]
    if not valid:
        return None
    min_x = min(e[0] for e in valid)
    min_y = min(e[1] for e in valid)
    max_x = max(e[2] for e in valid)
    max_y = max(e[3] for e in valid)
    return [min_x, min_y, max_x, max_y]


def _min_zoom(zooms: list[int | None]) -> int | None:
    """Most permissive min_zoom: the minimum (most zoomed-out) of all layers."""
    valid = [z for z in zooms if z is not None]
    return min(valid) if valid else None


def _max_zoom(zooms: list[int | None]) -> int | None:
    """Most permissive max_zoom: the maximum (most zoomed-in) of all layers."""
    valid = [z for z in zooms if z is not None]
    return max(valid) if valid else None
