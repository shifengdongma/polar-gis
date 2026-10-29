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
    gwc_3413_backfill: bool = True
    batch_parallel_workers: int = 8
    query_result_limit: int = 1000
    demo_data_enabled: bool = True
    ice_enabled: bool = True
    ice_data_root: Path = Path("/data/ice")
    ice_tile_cache_entries: int = 256
    ice_tile_max_zoom: int = 10
    s57_basemap_source_root: str = "/data/s57-basemaps"
    s57_basemap_profile: str = "global_overview_v1"
    s57_basemap_allow_local_source: bool = True

    # Navigation / environment
    navigation_enabled: bool = True
    navigation_data_root: Path = Path("/data/navigation")
    navigation_ice_data_root: Path | None = None
    navigation_ice_backend: str = "auto"
    navigation_manifest_path: Path | None = None
    navigation_default_data_policy: str = "real_only"
    navigation_allow_future_match: bool = False
    navigation_max_lag_wind_hours: float = 6.0
    navigation_max_lag_ice_hours: float = 24.0
    navigation_max_lag_current_hours: float = 24.0
    navigation_max_lag_wave_hours: float = 24.0
    navigation_tile_cache_entries: int = 256
    navigation_tile_max_zoom: int = 8
    navigation_max_batch_points: int = 500
    navigation_field_max_points: int = 900

    # Planner / planning tasks
    planner_max_cells: int = 20000
    planner_max_candidates: int = 20
    planner_max_generations: int = 100
    planner_population_size: int = 36
    planner_timeout_seconds: int = 300
    planner_max_concurrent_jobs: int = 1
    planner_max_queued_runs: int = 10
    planner_max_retained_runs: int = 100
    planner_result_root: Path = Path("storage/navigation/plans")
    planner_risk_grid_max_cells: int = 20000
    planner_max_route_points: int = 1000

    initial_admin_username: str | None = None
    initial_admin_password: str | None = Field(default=None, repr=False)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def resolved_navigation_ice_data_root(self) -> Path:
        """Ice files are shared with the existing ice layer unless explicitly overridden."""
        return self.navigation_ice_data_root or self.ice_data_root

    @property
    def resolved_navigation_manifest_path(self) -> Path:
        return self.navigation_manifest_path or (
            self.navigation_data_root / "navigation_manifest.json"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
