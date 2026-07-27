from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.core.errors import AppError


class GeoServerClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.geoserver_url.rstrip("/")
        self.auth = httpx.BasicAuth(
            settings.geoserver_admin_user,
            settings.geoserver_admin_password,
        )

    def _request(
        self,
        method: str,
        path: str,
        allowed_statuses: set[int] | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        try:
            response = httpx.request(
                method,
                f"{self.base_url}/rest/{path.lstrip('/')}",
                auth=self.auth,
                timeout=30,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise AppError("GEOSERVER_UNAVAILABLE", "GeoServer连接失败", 503) from exc
        allowed = allowed_statuses or {200, 201, 202, 204, 409}
        if response.status_code not in allowed:
            raise AppError(
                "GEOSERVER_PUBLISH_FAILED",
                "GeoServer资源发布失败",
                502,
                response.text[-2000:],
            )
        return response

    def ensure_workspace(self) -> None:
        workspace = self.settings.geoserver_workspace
        response = self._request(
            "GET",
            f"workspaces/{workspace}.json",
            allowed_statuses={200, 404},
        )
        if response.status_code == 404:
            self._request("POST", "workspaces", json={"workspace": {"name": workspace}})

    def ensure_postgis_store(self, store_name: str = "postgis") -> None:
        workspace = self.settings.geoserver_workspace
        parsed = urlparse(self.settings.database_url.replace("postgresql+psycopg", "postgresql"))
        payload = {
            "dataStore": {
                "name": store_name,
                "connectionParameters": {
                    "host": parsed.hostname,
                    "port": str(parsed.port or 5432),
                    "database": parsed.path.lstrip("/"),
                    "user": parsed.username,
                    "passwd": parsed.password,
                    "dbtype": "postgis",
                    "schema": "geo",
                },
            }
        }
        response = self._request(
            "GET",
            f"workspaces/{workspace}/datastores/{store_name}.json",
            allowed_statuses={200, 404},
        )
        if response.status_code == 404:
            self._request("POST", f"workspaces/{workspace}/datastores", json=payload)

    def publish_feature_type(
        self,
        table_name: str,
        layer_name: str,
        title: str,
        store_name: str = "postgis",
    ) -> None:
        self.ensure_workspace()
        self.ensure_postgis_store(store_name)
        workspace = self.settings.geoserver_workspace
        payload = {
            "featureType": {
                "name": layer_name,
                "nativeName": table_name,
                "title": title,
                "enabled": True,
                "nativeBoundingBox": {
                    "minx": -180,
                    "maxx": 180,
                    "miny": -90,
                    "maxy": 90,
                    "crs": "EPSG:4326",
                },
                "latLonBoundingBox": {
                    "minx": -180,
                    "maxx": 180,
                    "miny": -90,
                    "maxy": 90,
                    "crs": "EPSG:4326",
                },
            }
        }
        self._request(
            "POST",
            f"workspaces/{workspace}/datastores/{store_name}/featuretypes",
            json=payload,
        )

    def publish_feature_types_batch(
        self,
        layers: list[dict],
        store_name: str = "postgis",
    ) -> None:
        self.ensure_workspace()
        self.ensure_postgis_store(store_name)
        workspace = self.settings.geoserver_workspace
        for spec in layers:
            payload = {
                "featureType": {
                    "name": spec["layer_name"],
                    "nativeName": spec["table_name"],
                    "title": spec["title"],
                    "enabled": True,
                    "nativeBoundingBox": {
                        "minx": -180,
                        "maxx": 180,
                        "miny": -90,
                        "maxy": 90,
                        "crs": "EPSG:4326",
                    },
                    "latLonBoundingBox": {
                        "minx": -180,
                        "maxx": 180,
                        "miny": -90,
                        "maxy": 90,
                        "crs": "EPSG:4326",
                    },
                }
            }
            self._request(
                "POST",
                f"workspaces/{workspace}/datastores/{store_name}/featuretypes",
                json=payload,
            )

    def publish_geotiff(self, path: str, layer_name: str) -> None:
        self.ensure_workspace()
        workspace = self.settings.geoserver_workspace
        self._request(
            "PUT",
            f"workspaces/{workspace}/coveragestores/{layer_name}/external.geotiff?configure=first&coverageName={layer_name}",
            content=f"file:{path}",
            headers={"Content-Type": "text/plain"},
        )

    def publish_style(self, style_name: str, sld: str) -> None:
        self.ensure_workspace()
        workspace = self.settings.geoserver_workspace
        response = self._request(
            "GET",
            f"workspaces/{workspace}/styles/{style_name}.json",
            allowed_statuses={200, 404},
        )
        if response.status_code == 404:
            self._request(
                "POST",
                f"workspaces/{workspace}/styles?name={style_name}",
                content=sld,
                headers={"Content-Type": "application/vnd.ogc.sld+xml"},
            )
        else:
            self._request(
                "PUT",
                f"workspaces/{workspace}/styles/{style_name}",
                content=sld,
                headers={"Content-Type": "application/vnd.ogc.sld+xml"},
            )

    def set_default_style(self, layer_name: str, style_name: str) -> None:
        workspace = self.settings.geoserver_workspace
        self._request(
            "PUT",
            f"layers/{workspace}:{layer_name}",
            json={
                "layer": {
                    "defaultStyle": {
                        "name": style_name,
                        "workspace": workspace,
                    }
                }
            },
        )

    def delete_layer_resource(self, layer_name: str, is_raster: bool) -> None:
        workspace = self.settings.geoserver_workspace
        if is_raster:
            path = f"workspaces/{workspace}/coveragestores/{layer_name}?recurse=true"
        else:
            path = (
                f"workspaces/{workspace}/datastores/postgis/featuretypes/"
                f"{layer_name}?recurse=true"
            )
        self._request("DELETE", path, allowed_statuses={200, 202, 204, 404})

    # ── Layer Group ─────────────────────────────────────────────────

    def create_or_update_layer_group(
        self, group_name: str, layer_names: list[str], mode: str = "SINGLE"
    ) -> None:
        """Create or update a GeoServer layer group.

        Uses PUT for idempotent upsert — updates if exists, creates if not.
        """
        self.ensure_workspace()
        workspace = self.settings.geoserver_workspace

        payload = {
            "layerGroup": {
                "name": group_name,
                "mode": mode,
                "title": group_name,
                "workspace": {"name": workspace},
                "publishables": {
                    "published": [
                        {"@type": "layer", "name": f"{workspace}:{ln}"}
                        for ln in layer_names
                    ]
                },
                "styles": {
                    "style": [{} for _ in layer_names],
                },
            }
        }

        # check if exists
        check = self._request(
            "GET",
            f"workspaces/{workspace}/layergroups/{group_name}.json",
            allowed_statuses={200, 404},
        )
        if check.status_code == 200:
            # update
            self._request(
                "PUT",
                f"workspaces/{workspace}/layergroups/{group_name}",
                json=payload,
            )
        else:
            self._request(
                "POST",
                "layergroups",
                json=payload,
            )

    def delete_layer_group_if_unreferenced(self, group_name: str) -> bool:
        """Delete a layer group; return True if deleted, False if not found."""
        workspace = self.settings.geoserver_workspace
        resp = self._request(
            "DELETE",
            f"workspaces/{workspace}/layergroups/{group_name}?recurse=true",
            allowed_statuses={200, 202, 204, 404},
        )
        return resp.status_code != 404

    # ── GeoWebCache (GWC) ───────────────────────────────────────────

    def ensure_gwc_layer(
        self,
        layer_name: str,
        gridsets: list[str] | None = None,
        mime_formats: list[str] | None = None,
    ) -> None:
        """Enable GWC tile caching for a layer or layer group.

        PUT /rest/gwc/layers/{qualified_name}.json
        """
        if gridsets is None:
            gridsets = ["EPSG:3857", "EPSG:4326"]
        if mime_formats is None:
            mime_formats = ["image/png", "image/jpeg"]

        workspace = self.settings.geoserver_workspace
        qualified = f"{workspace}:{layer_name}"

        payload = {
            "GeoServerLayer": {
                "name": qualified,
                "enabled": True,
                "mimeFormats": mime_formats,
                "gridSubsets": [
                    {"gridSetName": gs} for gs in gridsets
                ],
                "metaWidthHeight": [4, 4],
                "expireCache": 0,
                "expireClients": 0,
                "gutter": 0,
            }
        }

        self._request(
            "PUT",
            f"gwc/layers/{qualified}.json",
            json=payload,
            allowed_statuses={200, 201, 204},
        )

    def ensure_gridset(self, gridset_name: str, crs: str, extent: list[float]) -> None:
        """Create or update a GWC gridset.

        PUT /rest/gwc/gridsets/{name}.json
        """
        payload = {
            "id": gridset_name,
            "crs": {
                "@class": "org.geotools.referencing.CRS",
                "value": crs,
            },
            "tileWidth": 256,
            "tileHeight": 256,
            "extent": {
                "minx": extent[0],
                "miny": extent[1],
                "maxx": extent[2],
                "maxy": extent[3],
            },
            "levels": _default_gridset_levels(extent),
        }

        self._request(
            "PUT",
            f"gwc/gridsets/{gridset_name}.json",
            json=payload,
            allowed_statuses={200, 201, 204},
        )

    def truncate_layer_cache(self, layer_name: str) -> None:
        """Truncate (clear) the tile cache for a GWC layer."""
        workspace = self.settings.geoserver_workspace
        qualified = f"{workspace}:{layer_name}"
        self._request(
            "DELETE",
            f"gwc/rest/masstruncate/{qualified}",
            allowed_statuses={200, 202, 204, 404},
        )

    def seed_layer_cache(
        self,
        layer_name: str,
        gridset: str = "EPSG:3857",
        zoom_start: int = 0,
        zoom_stop: int = 5,
    ) -> None:
        """Seed (pre-generate) GWC tiles for a range of zoom levels."""
        workspace = self.settings.geoserver_workspace
        qualified = f"{workspace}:{layer_name}"
        payload = {
            "seedRequest": {
                "name": qualified,
                "gridSetId": gridset,
                "zoomStart": zoom_start,
                "zoomStop": zoom_stop,
                "type": "seed",
                "threadCount": 4,
            }
        }
        self._request(
            "POST",
            "gwc/rest/seed.json",
            json=payload,
            allowed_statuses={200, 201, 202, 204},
        )


# ── helpers ──────────────────────────────────────────────────────────

def _default_gridset_levels(extent: list[float]) -> list[dict]:
    """Generate reasonable zoom levels for a gridset."""
    dx = extent[2] - extent[0]
    if dx <= 0:
        dx = 360.0
    base_resolution = dx / 256.0
    levels = []
    for i in range(22):
        resolution = base_resolution / (2 ** i)
        scale_denom = resolution / 0.00028  # approx
        levels.append({
            "resolution": resolution,
            "scaleDenominator": scale_denom,
        })
    return levels
