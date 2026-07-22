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
