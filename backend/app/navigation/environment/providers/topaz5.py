"""TOPAZ5 current provider: native polar grid, rotated to geographic EN."""

from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime
from math import atan2, cos, degrees, hypot, radians, sin
from pathlib import Path
from threading import RLock

import numpy as np
from netCDF4 import Dataset, num2date
from pyproj import CRS, Geod, Transformer

from app.navigation.contracts import DataQuality, TimeMatchInfo
from app.navigation.environment.manifest import EnvironmentManifest
from app.navigation.environment.models import ProviderSample
from app.navigation.environment.providers.base import BaseEnvironmentProvider
from app.navigation.environment.time_manager import select_time
from app.navigation.netcdf import open_netcdf

_TOPAZ_PROJ4 = "+proj=stere +lat_0=90 +lon_0=-45 +k=1 +R=6378273 +units=m +no_defs"
_TOPAZ_CRS = CRS.from_proj4(_TOPAZ_PROJ4)
_WGS84 = CRS.from_epsg(4326)
_100KM = 100_000.0


class TOPAZ5CurrentProvider(BaseEnvironmentProvider):
    field = "current"
    source_name = "TOPAZ5"

    def __init__(self, data_root: Path, manifest: EnvironmentManifest) -> None:
        self.data_root = Path(data_root)
        self.manifest = manifest
        search_root = self.data_root / "current" if (self.data_root / "current").is_dir() else self.data_root
        pattern = manifest.field("current").glob or "Copernicus_current_*.nc"
        paths = sorted(search_root.glob(pattern)) if search_root.is_dir() else []
        self._paths_by_date = {
            parsed: path for path in paths if (parsed := _file_date(path)) is not None
        }
        self._lock = RLock()
        self._to_topaz = Transformer.from_crs(_WGS84, _TOPAZ_CRS, always_xy=True)
        self._to_wgs84 = Transformer.from_crs(_TOPAZ_CRS, _WGS84, always_xy=True)
        self._geod = Geod(ellps="WGS84")
        self._dataset: Dataset | None = None
        self._active_path: Path | None = None
        self._x: np.ndarray | None = None
        self._y: np.ndarray | None = None
        self._times: list[datetime] = []
        self._issue_time: datetime | None = None
        self._time_index: int | None = None
        self._u_slice: np.ma.MaskedArray | None = None
        self._v_slice: np.ma.MaskedArray | None = None
        self._units = "m/s"
        self._xy_scale = _100KM
        self._slice_cache: OrderedDict[int, tuple[np.ma.MaskedArray, np.ma.MaskedArray]] = OrderedDict()

    def available(self) -> bool:
        return bool(self._paths_by_date)

    def times(self) -> list[datetime]:
        return sorted(self._paths_by_date)

    def sample(
        self,
        longitude: float,
        latitude: float,
        requested_time: datetime,
        *,
        max_lag_hours: float | None,
        allow_future: bool,
    ) -> ProviderSample:
        requested = _utc(requested_time)
        if not self.available():
            return _unavailable(requested, "current_file_missing")
        dates = sorted(self._paths_by_date)
        candidates = [date for date in dates if allow_future or date <= requested]
        if not candidates:
            return _unavailable(requested, "no_data_at_or_before_requested_time")
        date = candidates[-1]
        selection = None
        try:
            with self._lock:
                self._activate(self._paths_by_date[date])
                selection = select_time(
                    self._times,
                    requested,
                    max_lag_hours=max_lag_hours,
                    allow_future=allow_future,
                    issue_times=[self._issue_time] * len(self._times),
                )
                if not selection.available or selection.index is None:
                    return _unavailable(
                        requested,
                        selection.reason or "current_time_unavailable",
                        selection.match_info(),
                    )
                self._load_slice(selection.index)
                assert self._x is not None and self._y is not None
                x_file, y_file = self._wgs84_to_native(longitude, latitude)
                column0, column1, dx = _bracket(self._x, x_file)
                row0, row1, dy = _bracket(self._y, y_file)
                assert self._u_slice is not None and self._v_slice is not None
                raw_u = _bilinear(self._u_slice, row0, row1, column0, column1, dy, dx)
                raw_v = _bilinear(self._v_slice, row0, row1, column0, column1, dy, dx)
                scale = 0.01 if self._units == "cm/s" else 1.0
                east, north = self._geographic_components(
                    longitude, latitude, raw_u * scale, raw_v * scale
                )
                speed = hypot(east, north)
                direction_to = (degrees(atan2(east, north)) + 360.0) % 360.0
                return ProviderSample(
                    available=True,
                    values={
                        "uMs": east,
                        "vMs": north,
                        "speedMs": speed,
                        "directionToDeg": direction_to,
                    },
                    units={
                        "uMs": "m/s",
                        "vMs": "m/s",
                        "speedMs": "m/s",
                        "directionToDeg": "degree",
                    },
                    component_quality={
                        key: DataQuality.REAL
                        for key in ("uMs", "vMs", "speedMs", "directionToDeg")
                    },
                    source=self.source_name,
                    time=selection.match_info(),
                )
        except Exception as error:  # noqa: BLE001
            return _unavailable(
                requested,
                f"current_read_error:{type(error).__name__}",
                selection.match_info() if selection is not None and selection.matched_time else None,
            )

    def close(self) -> None:
        with self._lock:
            if self._dataset is not None:
                self._dataset.close()
            self._dataset = None
            self._active_path = None
            self._x = None
            self._y = None
            self._times = []
            self._time_index = None
            self._u_slice = None
            self._v_slice = None
            self._slice_cache.clear()

    def _activate(self, path: Path) -> None:
        if self._active_path == path and self._dataset is not None:
            return
        dataset = open_netcdf(path)
        try:
            required = {"x", "y", "time", "vxo", "vyo"}
            missing = required.difference(dataset.variables)
            if missing:
                raise ValueError(f"TOPAZ5 file is missing: {', '.join(sorted(missing))}")
            x = np.asarray(dataset.variables["x"][:], dtype=np.float64)
            y = np.asarray(dataset.variables["y"][:], dtype=np.float64)
            times = _read_times(dataset)
        except Exception:
            dataset.close()
            raise
        if self._dataset is not None:
            self._dataset.close()
        self._dataset = dataset
        self._active_path = path
        self._xy_scale = _100KM if np.nanmax(np.abs(x), initial=0.0) < 1_000_000.0 else 1.0
        self._x = x
        self._y = y
        self._times = times
        self._issue_time = _read_issue_time(dataset)
        self._time_index = None
        self._u_slice = None
        self._v_slice = None
        self._slice_cache.clear()
        units = str(getattr(dataset.variables["vxo"], "units", "m/s")).strip().casefold().replace(" ", "")
        self._units = "cm/s" if units in {"cm/s", "cms-1", "cm.s-1", "cmps"} else "m/s"

    def _load_slice(self, time_index: int) -> None:
        if self._time_index == time_index:
            return
        cached = self._slice_cache.pop(time_index, None)
        if cached is not None:
            self._u_slice, self._v_slice = cached
            self._slice_cache[time_index] = cached
            self._time_index = time_index
            return
        assert self._dataset is not None
        u = np.ma.masked_invalid(
            np.ma.asarray(self._dataset.variables["vxo"][time_index, :, :], dtype=np.float64)
        )
        v = np.ma.masked_invalid(
            np.ma.asarray(self._dataset.variables["vyo"][time_index, :, :], dtype=np.float64)
        )
        self._u_slice = u
        self._v_slice = v
        self._slice_cache[time_index] = (u, v)
        while len(self._slice_cache) > 3:
            self._slice_cache.popitem(last=False)
        self._time_index = time_index

    def _wgs84_to_native(self, longitude: float, latitude: float) -> tuple[float, float]:
        x_m, y_m = self._to_topaz.transform(longitude, latitude)
        return x_m / self._xy_scale, y_m / self._xy_scale

    def _geographic_components(
        self, longitude: float, latitude: float, vxo: float, vyo: float
    ) -> tuple[float, float]:
        x_m, y_m = self._to_topaz.transform(longitude, latitude)
        lon0, lat0 = self._to_wgs84.transform(x_m, y_m)
        lon_x, lat_x = self._to_wgs84.transform(x_m + 1000.0, y_m)
        lon_y, lat_y = self._to_wgs84.transform(x_m, y_m + 1000.0)
        azimuth_x = radians(self._geod.inv(lon0, lat0, lon_x, lat_x)[0])
        azimuth_y = radians(self._geod.inv(lon0, lat0, lon_y, lat_y)[0])
        east = vxo * sin(azimuth_x) + vyo * sin(azimuth_y)
        north = vxo * cos(azimuth_x) + vyo * cos(azimuth_y)
        return float(east), float(north)


def _bracket(axis: np.ndarray, value: float) -> tuple[int, int, float]:
    minimum, maximum = float(np.min(axis)), float(np.max(axis))
    if value < minimum or value > maximum:
        raise ValueError("Point is outside current coverage.")
    ascending = axis[0] < axis[-1]
    ordered = axis if ascending else axis[::-1]
    upper_ordered = int(np.searchsorted(ordered, value, side="right"))
    upper_ordered = min(max(upper_ordered, 1), len(axis) - 1)
    lower_ordered = upper_ordered - 1
    lower = lower_ordered if ascending else len(axis) - 1 - lower_ordered
    upper = upper_ordered if ascending else len(axis) - 1 - upper_ordered
    denominator = float(axis[upper] - axis[lower])
    fraction = 0.0 if denominator == 0 else (value - float(axis[lower])) / denominator
    return lower, upper, float(fraction)


def _bilinear(
    values: np.ma.MaskedArray,
    row0: int,
    row1: int,
    column0: int,
    column1: int,
    dy: float,
    dx: float,
) -> float:
    corners = np.ma.asarray(values[[row0, row0, row1, row1], [column0, column1, column0, column1]])
    raw = np.asarray(corners.filled(np.nan), dtype=np.float64)
    if np.any(np.ma.getmaskarray(corners)) or not np.all(np.isfinite(raw)):
        raise ValueError("No current data at requested location.")
    weights = np.array([(1 - dy) * (1 - dx), (1 - dy) * dx, dy * (1 - dx), dy * dx])
    return float(np.dot(raw, weights))


def _read_times(dataset: Dataset) -> list[datetime]:
    variable = dataset.variables["time"]
    values = num2date(
        variable[:],
        units=variable.units,
        calendar=getattr(variable, "calendar", "standard"),
        only_use_cftime_datetimes=False,
    )
    return [_as_utc(value) for value in np.atleast_1d(values)]


def _read_issue_time(dataset: Dataset) -> datetime | None:
    for name in ("forecast_reference_time", "issue_time"):
        variable = dataset.variables.get(name)
        if variable is not None and hasattr(variable, "units"):
            values = np.atleast_1d(
                num2date(
                    variable[:],
                    units=variable.units,
                    calendar=getattr(variable, "calendar", "standard"),
                    only_use_cftime_datetimes=False,
                )
            ).reshape(-1)
            return _as_utc(values[0]) if values.size else None
        if name in dataset.ncattrs():
            return _parse_datetime(dataset.getncattr(name))
    return None


def _file_date(path: Path) -> datetime | None:
    digits = "".join(ch for ch in path.stem if ch.isdigit())
    if len(digits) < 8:
        return None
    try:
        return datetime.strptime(digits[-8:], "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _parse_datetime(value) -> datetime | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return _as_utc(value) if value is not None else None


def _unavailable(
    requested_time: datetime,
    reason: str,
    match: TimeMatchInfo | None = None,
) -> ProviderSample:
    return ProviderSample(
        available=False,
        source="TOPAZ5",
        time=match or TimeMatchInfo(requested_time=requested_time),
        reason=reason,
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _as_utc(value) -> datetime:
    if isinstance(value, datetime):
        return _utc(value)
    return datetime(
        value.year,
        value.month,
        value.day,
        getattr(value, "hour", 0),
        getattr(value, "minute", 0),
        getattr(value, "second", 0),
        tzinfo=UTC,
    )
