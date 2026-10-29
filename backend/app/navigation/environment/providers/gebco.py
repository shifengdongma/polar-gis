"""GEBCO bathymetry provider: NetCDF elevation in metres, depth positive down."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from io import BytesIO
from math import pi
from pathlib import Path

import numpy as np
from netCDF4 import Dataset
from PIL import Image
from pyproj import Transformer

from app.navigation.contracts import DataQuality, TimeMatchInfo
from app.navigation.environment.manifest import EnvironmentManifest
from app.navigation.environment.models import ProviderSample
from app.navigation.environment.providers.base import (
    BaseEnvironmentProvider,
    ProviderUnavailable,
)
from app.navigation.netcdf import open_netcdf

_TILE_SIZE = 256
_WEB_MERCATOR_HALF = pi * 6378137.0
_POLAR_HALF = 4194304.0


class GEBCOBathymetryProvider(BaseEnvironmentProvider):
    field = "bathymetry"
    source_name = "GEBCO"

    def __init__(
        self,
        data_root: Path,
        manifest: EnvironmentManifest,
        *,
        tile_cache_entries: int = 128,
        max_zoom: int = 8,
    ) -> None:
        self.data_root = Path(data_root)
        self.manifest = manifest
        pattern = manifest.field("bathymetry").glob or "*.nc"
        search_root = self.data_root / "bathymetry" if (self.data_root / "bathymetry").is_dir() else self.data_root
        candidates = sorted(search_root.glob(pattern)) if search_root.is_dir() else []
        self.path = candidates[0] if candidates else None
        self.source_name = manifest.source("bathymetry", self.source_name) or self.source_name
        self._dataset: Dataset | None = None
        self._latitude: np.ndarray | None = None
        self._longitude: np.ndarray | None = None
        self._elevation: np.ndarray | None = None
        # Coordinate coverage is independent of the (potentially huge)
        # elevation array; cache it so per-point out-of-coverage checks never
        # rescan the grid.
        self._coverage: dict[str, float] | None = None
        self._tiles: OrderedDict[tuple[int, int, int, str], bytes] = OrderedDict()
        self._tile_cache_entries = tile_cache_entries
        self.max_zoom = max_zoom

    def available(self) -> bool:
        return self.path is not None and self.path.is_file()

    def times(self) -> list[datetime]:
        return []

    def coverage(self) -> dict[str, float] | None:
        if not self.available():
            return None
        if self._coverage is None:
            latitude, longitude = self._coordinate_axes()
            self._coverage = {
                "minLatitude": float(np.nanmin(latitude)),
                "maxLatitude": float(np.nanmax(latitude)),
                "minLongitude": float(np.nanmin(longitude)),
                "maxLongitude": float(np.nanmax(longitude)),
            }
        return self._coverage

    def sample(
        self,
        longitude: float,
        latitude: float,
        requested_time: datetime,
        *,
        max_lag_hours: float | None,
        allow_future: bool,
    ) -> ProviderSample:
        time = TimeMatchInfo(requested_time=requested_time, match_policy="latest_not_after")
        if not self.available():
            return ProviderSample(
                available=False,
                source=self.source_name,
                time=time,
                reason="bathymetry_file_missing",
            )
        try:
            # Read the coordinate axes first.  The elevation array can be
            # hundreds of MB, so an out-of-coverage point must not force it to
            # load.
            lat_axis, lon_axis = self._coordinate_axes()
        except Exception as error:  # noqa: BLE001 - provider failure is data, not app failure
            return ProviderSample(
                available=False,
                source=self.source_name,
                time=time,
                reason=f"bathymetry_read_error:{type(error).__name__}",
            )
        lat_index = _nearest_index(lat_axis, latitude)
        lon_index = _nearest_index(lon_axis, _wrap_longitude(longitude, lon_axis))
        if lat_index is None or lon_index is None:
            return ProviderSample(
                available=False,
                source=self.source_name,
                time=time,
                reason="out_of_coverage",
                coverage=self.coverage(),
            )
        try:
            elevation = self._elevation_grid()
        except Exception as error:  # noqa: BLE001
            return ProviderSample(
                available=False,
                source=self.source_name,
                time=time,
                reason=f"bathymetry_read_error:{type(error).__name__}",
            )
        raw = float(elevation[lat_index, lon_index])
        if not np.isfinite(raw):
            return ProviderSample(
                available=False,
                source=self.source_name,
                time=time,
                reason="no_data",
                coverage=self._coverage,
            )
        depth = max(0.0, -raw)
        return ProviderSample(
            available=True,
            values={"depthM": depth, "isLand": raw >= 0.0},
            units={"depthM": "m"},
            component_quality={"depthM": DataQuality.REAL},
            source=self.source_name,
            time=time,
            coverage=self._coverage,
        )

    def tile(self, crs: str, z: int, x: int, y: int) -> bytes:
        if not self.available():
            raise ProviderUnavailable("bathymetry_file_missing")
        if z < 0 or z > self.max_zoom:
            raise ProviderUnavailable("zoom_out_of_range")
        key = (z, x, y, crs)
        cached = self._tiles.pop(key, None)
        if cached is not None:
            self._tiles[key] = cached
            return cached
        png = self._render_tile(crs, z, x, y)
        self._tiles[key] = png
        while len(self._tiles) > self._tile_cache_entries:
            self._tiles.popitem(last=False)
        return png

    def _render_tile(self, crs: str, z: int, x: int, y: int) -> bytes:
        lat_axis, lon_axis, elevation = self._grid()
        half = _POLAR_HALF if crs == "EPSG:3413" else _WEB_MERCATOR_HALF
        tile_count = 1 << z
        if x < 0 or y < 0 or x >= tile_count or y >= tile_count:
            raise ProviderUnavailable("tile_out_of_range")
        resolution = (2.0 * half) / tile_count
        x_min = -half + x * resolution
        y_max = half - y * resolution
        step = resolution / _TILE_SIZE
        xs = x_min + (np.arange(_TILE_SIZE) + 0.5) * step
        ys = y_max - (np.arange(_TILE_SIZE) + 0.5) * step
        grid_x, grid_y = np.meshgrid(xs, ys)
        transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(grid_x, grid_y)
        lat_idx = _nearest_indices(lat_axis, lat)
        lon_idx = _nearest_indices(lon_axis, _wrap_longitudes(lon, lon_axis))
        rgba = np.zeros((_TILE_SIZE, _TILE_SIZE, 4), dtype=np.uint8)
        valid = np.isfinite(lat_idx) & np.isfinite(lon_idx)
        if valid.any():
            rows = lat_idx[valid].astype(int)
            columns = lon_idx[valid].astype(int)
            values = elevation[rows, columns]
            water = np.isfinite(values) & (values < 0)
            depth = np.maximum(-np.nan_to_num(values, nan=0.0), 0.0)
            scale = np.clip(np.log1p(depth) / np.log1p(6000.0), 0.0, 1.0)
            rgba[valid, 0] = (105 - 90 * scale).astype(np.uint8)
            rgba[valid, 1] = (205 - 135 * scale).astype(np.uint8)
            rgba[valid, 2] = (235 - 95 * scale).astype(np.uint8)
            rgba[valid, 3] = np.where(water, 175, 0).astype(np.uint8)
        image = Image.fromarray(rgba, mode="RGBA")
        output = BytesIO()
        image.save(output, format="PNG", compress_level=1)
        return output.getvalue()

    def close(self) -> None:
        if self._dataset is not None:
            self._dataset.close()
        self._dataset = None
        self._latitude = None
        self._longitude = None
        self._elevation = None
        self._coverage = None

    def _axes(self) -> tuple[np.ndarray, np.ndarray]:
        return self._coordinate_axes()

    def _grid(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        latitude, longitude = self._coordinate_axes()
        return latitude, longitude, self._elevation_grid()

    def _coordinate_axes(self) -> tuple[np.ndarray, np.ndarray]:
        """Read only the 1-D coordinate axes (no elevation array)."""
        if self._latitude is not None and self._longitude is not None:
            return self._latitude, self._longitude
        if self.path is None:
            raise ProviderUnavailable("bathymetry_file_missing")
        dataset = self._dataset or open_netcdf(self.path)
        try:
            lat_name, lon_name = _find_lat_lon(dataset)
            latitude = np.asarray(dataset.variables[lat_name][:], dtype=np.float64)
            longitude = np.asarray(dataset.variables[lon_name][:], dtype=np.float64)
            if latitude.ndim != 1 or longitude.ndim != 1:
                raise ValueError("GEBCO latitude/longitude must be one-dimensional.")
        except Exception:
            if self._dataset is None:
                dataset.close()
            raise
        self._dataset = dataset
        self._latitude = latitude
        self._longitude = longitude
        return latitude, longitude

    def _elevation_grid(self) -> np.ndarray:
        """Load the elevation array once, after coverage has been validated."""
        if self._elevation is not None:
            return self._elevation
        if self.path is None:
            raise ProviderUnavailable("bathymetry_file_missing")
        self._coordinate_axes()
        assert self._dataset is not None
        try:
            elevation_name = _find_elevation(self._dataset)
            elevation_variable = self._dataset.variables[elevation_name]
            units = str(getattr(elevation_variable, "units", "")).strip().casefold()
            if units not in {"m", "meter", "meters", "metre", "metres"}:
                raise ValueError("GEBCO elevation must use metres.")
            self._elevation = np.ma.asarray(
                elevation_variable[:], dtype=np.float64
            ).filled(np.nan)
        except Exception:
            self._dataset.close()
            self._dataset = None
            self._latitude = None
            self._longitude = None
            raise
        return self._elevation


def _find_lat_lon(dataset: Dataset) -> tuple[str, str]:
    by_case = {name.casefold(): name for name in dataset.variables}
    lat = next((by_case[name] for name in ("latitude", "lat", "y") if name in by_case), None)
    lon = next((by_case[name] for name in ("longitude", "lon", "x") if name in by_case), None)
    if lat is None or lon is None:
        raise ValueError("GEBCO dataset has no latitude/longitude coordinates.")
    return lat, lon


def _find_elevation(dataset: Dataset) -> str:
    for name, variable in dataset.variables.items():
        if getattr(variable, "standard_name", None) == "height_above_mean_sea_level":
            return name
    by_case = {name.casefold(): name for name in dataset.variables}
    for alias in ("elevation", "z", "height"):
        if alias in by_case:
            return by_case[alias]
    raise ValueError("GEBCO dataset has no elevation variable.")


def _nearest_index(axis: np.ndarray, value: float) -> int | None:
    if axis.size == 0:
        return None
    low, high = float(np.min(axis)), float(np.max(axis))
    if value < low or value > high:
        return None
    ascending = axis if axis[0] <= axis[-1] else axis[::-1]
    index = int(np.searchsorted(ascending, value))
    index = min(max(index, 0), ascending.size - 1)
    if index and abs(ascending[index - 1] - value) <= abs(ascending[index] - value):
        index -= 1
    return index if axis[0] <= axis[-1] else axis.size - 1 - index


def _nearest_indices(axis: np.ndarray, values: np.ndarray) -> np.ndarray:
    result = np.full(values.shape, np.nan, dtype=np.float64)
    finite = np.isfinite(values)
    if not finite.any() or axis.size == 0:
        return result
    low, high = float(np.min(axis)), float(np.max(axis))
    in_range = finite & (values >= low) & (values <= high)
    if not in_range.any():
        return result
    ascending = axis if axis[0] <= axis[-1] else axis[::-1]
    indices = np.searchsorted(ascending, values[in_range])
    indices = np.clip(indices, 0, ascending.size - 1)
    lower = np.maximum(indices - 1, 0)
    choose_lower = np.abs(ascending[lower] - values[in_range]) <= np.abs(
        ascending[indices] - values[in_range]
    )
    indices = np.where(choose_lower, lower, indices)
    if axis[0] > axis[-1]:
        indices = axis.size - 1 - indices
    result[in_range] = indices
    return result


def _wrap_longitude(value: float, axis: np.ndarray) -> float:
    low, high = float(np.min(axis)), float(np.max(axis))
    if low >= 0.0 and high > 180.0:
        return value % 360.0
    if low < 0.0 and high <= 180.0:
        return (value + 180.0) % 360.0 - 180.0
    return value


def _wrap_longitudes(values: np.ndarray, axis: np.ndarray) -> np.ndarray:
    low, high = float(np.min(axis)), float(np.max(axis))
    if low >= 0.0 and high > 180.0:
        return values % 360.0
    if low < 0.0 and high <= 180.0:
        return (values + 180.0) % 360.0 - 180.0
    return values
