"""GWC WMTS tile-template helpers for the global overview basemaps.

GeoServer's *instance-wide* WMTS GetCapabilities document is not usable once a
workspace contains thousands of GWC layers: every layer repeats
``TileMatrixSetLimits`` for every zoom level of every gridset. On the current
deployment (~5.8k layers × 3 gridsets) the document is ~729 MB and takes ~33 s
to generate; with the image's default 1 GiB heap it fails with an
``OutOfMemoryError`` instead.

The overview basemaps are served from a single GWC layer group, so their tile
URLs are fully known at registration time. Storing a direct GetTile template
lets the frontend build the XYZ/WMTS source locally with the matching gridset
and skip GetCapabilities entirely.
"""

from __future__ import annotations

OVERVIEW_LAYER_GROUP = "polar_global_enc_overview"

# Names must stay in sync with ``BasemapPostProcessor._upsert_base_map`` callers.
OVERVIEW_BASEMAP_NAMES: dict[str, str] = {
    "EPSG:3857": "全球海图概览底图",
    "EPSG:3413": "全球海图概览底图（北极）",
}

# GWC's canonical Web Mercator matrix set is EPSG:900913, not EPSG:3857.
GWC_MATRIX_SET_BY_CRS: dict[str, str] = {
    "EPSG:3857": "EPSG:900913",
    "EPSG:3413": "EPSG:3413",
}

GWC_3413_GRIDSET = "EPSG:3413"
GWC_3413_CRS = "EPSG:3413"
GWC_3413_EXTENT = [-4194304.0, -4194304.0, 4194304.0, 4194304.0]
GWC_LAYER_GRIDSETS = ["EPSG:900913", "EPSG:4326", "EPSG:3413"]
GWC_LAYER_MIME_FORMATS = ["image/png"]


def overview_wmts_tile_template(public_url: str, workspace: str, crs: str) -> str:
    """Return a GWC WMTS GetTile URL template with ``{z}/{x}/{y}`` placeholders."""
    matrix_set = GWC_MATRIX_SET_BY_CRS.get(crs)
    if matrix_set is None:
        raise ValueError(f"unsupported overview basemap CRS: {crs}")
    base = f"{public_url.rstrip('/')}/gwc/service/wmts"
    layer = f"{workspace}:{OVERVIEW_LAYER_GROUP}"
    return (
        f"{base}?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
        f"&LAYER={layer}&STYLE="
        f"&TILEMATRIXSET={matrix_set}&FORMAT=image/png"
        f"&TILEMATRIX={matrix_set}:{{z}}&TILEROW={{y}}&TILECOL={{x}}"
    )
