from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "极地海洋环境信息平台"
    app_env: str = "development"
    app_secret_key: str = "development-only-change-me"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://polar_gis:polar_gis@localhost:5432/polar_gis"
    auto_create_schema: bool = False
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 7
    cookie_secure: bool = False
    cors_allowed_origins: str = "http://localhost:5173"
    storage_root: Path = Path("storage")
    temp_root: Path = Path("storage/temp")
    max_upload_bytes: int = 5 * 1024 * 1024 * 1024
    geoserver_url: str = "http://localhost:8080/geoserver"
    geoserver_public_url: str = "/geoserver"
    geoserver_admin_user: str = "admin"
    geoserver_admin_password: str = "geoserver"
    geoserver_workspace: str = "polar_gis"
    gdal_ogrinfo_command: str = "ogrinfo"
    gdal_ogr2ogr_command: str = "ogr2ogr"
    gdal_info_command: str = "gdalinfo"
    worker_poll_seconds: float = 2.0
    worker_heartbeat_seconds: int = 30
    batch_parallel_workers: int = 8
    query_result_limit: int = 1000
    demo_data_enabled: bool = True
    s57_basemap_source_root: str = "/data/s57-basemaps"
    s57_basemap_profile: str = "global_overview_v1"
    s57_basemap_allow_local_source: bool = True
    initial_admin_username: str | None = None
    initial_admin_password: str | None = Field(default=None, repr=False)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
