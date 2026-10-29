"""CARRA2 wind provider: paired ``si10``/``wdir10`` monthly NetCDF files."""

from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime
from math import atan2, cos, degrees, hypot, radians, sin
from pathlib import Path
from threading import RLock

import numpy as np
from netCDF4 import Dataset, num2date

from app.navigation.contracts import DataQuality, TimeMatchInfo
from app.navigation.environment.manifest import EnvironmentManifest
from app.navigation.environment.models import ProviderSample
from app.navigation.environment.providers.base import BaseEnvironmentProvider
from app.navigation.environment.time_manager import select_time
from app.navigation.netcdf import open_netcdf

_COARSE_STRIDE = 24
_MAX_DISTANCE_DEGREES = 0.5


class CARRA2WindProvider(BaseEnvironmentProvider):
    field = "wind"
    source_name = "CARRA2"

    def __init__(self, data_root: Path, manifest: EnvironmentManifest) -> None:
        self.data_root = Path(data_root)
        self.manifest = manifest
        search_root = self.data_root / "wind" if (self.data_root / "wind").is_dir() else self.data_root
        pattern = manifest.field("wind").glob or "*.nc"
        speed_paths: dict[datetime, Path] = {}
        direction_paths: dict[datetime, Path] = {}
        for path in sorted(search_root.glob(pattern)) if search_root.is_dir() else []:
            month = _file_month(path)
            if month is None:
                continue
            if "speed" in path.stem:
                speed_paths[month] = path
            elif "direction" in path.stem:
                direction_paths[month] = path
        self._paths_by_month = {
            month: (speed_paths[month], direction_paths[month])
            for month in sorted(speed_paths.keys() & direction_paths.keys())
        }
        self._lock = RLock()
        self._speed_dataset: Dataset | None = None
        self._direction_dataset: Dataset | None = None
        self._active_month: datetime | None = None
        self._latitude: np.ndarray | None = None
        self._longitude: np.ndarray | None = None
        self._coarse_latitude: np.ndarray | None = None
        self._coarse_longitude: np.ndarray | None = None
        self._times: list[datetime] = []
        self._time_index: int | None = None
        self._speed_slice: np.ma.MaskedArray | None = None
        self._direction_slice: np.ma.MaskedArray | None = None
        self._slice_cache: OrderedDict[int, tuple[np.ma.MaskedArray, np.ma.MaskedArray]] = OrderedDict()

    def available(self) -> bool:
        return bool(self._paths_by_month)

    def times(self) -> list[datetime]:
        return sorted(self._paths_by_month)

    def coverage(self) -> dict[str, float] | None:
        if not self.available():
            return None
        try:
            self._activate_month(next(iter(self._paths_by_month)))
            assert self._latitude is not None and self._longitude is not None
            return {
                "minLatitude": float(np.nanmin(self._latitude)),
                "maxLatitude": float(np.nanmax(self._latitude)),
                "minLongitude": float(np.nanmin(self._longitude)),
                "maxLongitude": float(np.nanmax(self._longitude)),
            }
        except Exception:  # noqa: BLE001
            return None

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
            return _unavailable(requested, "wind_file_missing")
        months = sorted(self._paths_by_month)
        month_candidates = [month for month in months if allow_future or month <= requested]
        if not month_candidates:
            return _unavailable(requested, "no_data_at_or_before_requested_time")
        month = month_candidates[-1]
        try:
            with self._lock:
                self._activate_month(month)
                selection = select_time(
                    self._times,
                    requested,
                    max_lag_hours=max_lag_hours,
                    allow_future=allow_future,
                )
                if not selection.available or selection.index is None:
                    return _unavailable(
                        requested,
                        selection.reason or "wind_time_unavailable",
                        selection.match_info(),
                    )
                self._load_slice(selection.index)
                assert self._latitude is not None and self._longitude is not None
                row, column, distance = self._nearest_grid_point(latitude, longitude)
                if distance > _MAX_DISTANCE_DEGREES:
                    return _unavailable(requested, "out_of_coverage", selection.match_info())
                assert self._speed_slice is not None and self._direction_slice is not None
                speed, direction_from, u, v = _wind_components(
                    self._speed_slice[row, column],
                    self._direction_slice[row, column],
                    self._convention,
                )
                return ProviderSample(
                    available=True,
                    values={
                        "speedMs": speed,
                        "directionFromDeg": direction_from,
                        "uMs": u,
                        "vMs": v,
                    },
                    units={
                        "speedMs": "m/s",
                        "directionFromDeg": "degree",
                        "uMs": "m/s",
                        "vMs": "m/s",
                    },
                    component_quality={
                        "speedMs": DataQuality.REAL,
                        "directionFromDeg": DataQuality.REAL,
                        "uMs": DataQuality.REAL,
                        "vMs": DataQuality.REAL,
                    },
                    source=self.source_name,
                    time=selection.match_info(),
                    coverage=self.coverage(),
                )
        except Exception as error:  # noqa: BLE001
            return _unavailable(requested, f"wind_read_error:{type(error).__name__}")

    def close(self) -> None:
        with self._lock:
            if self._speed_dataset is not None:
                self._speed_dataset.close()
            if self._direction_dataset is not None:
                self._direction_dataset.close()
            self._speed_dataset = None
            self._direction_dataset = None
            self._active_month = None
            self._time_index = None
            self._speed_slice = None
            self._direction_slice = None
            self._slice_cache.clear()

    def _activate_month(self, month: datetime) -> None:
        if self._active_month == month and self._speed_dataset is not None:
            return
        speed_path, direction_path = self._paths_by_month[month]
        speed_dataset = open_netcdf(speed_path)
        direction_dataset = open_netcdf(direction_path)
        try:
            speed_name, direction_name, convention = _resolve_variables(speed_dataset, direction_dataset)
            latitude = np.asarray(speed_dataset.variables["latitude"][:], dtype=np.float64)
            longitude = np.asarray(speed_dataset.variables["longitude"][:], dtype=np.float64)
            if latitude.ndim != 2 or longitude.shape != latitude.shape:
                raise ValueError("CARRA2 latitude/longitude must be matching two-dimensional grids.")
            speed_time = _read_times(speed_dataset)
            direction_time = _read_times(direction_dataset)
            if speed_time != direction_time or not speed_time:
                raise ValueError("CARRA2 speed/direction time axes do not align.")
        except Exception:
            speed_dataset.close()
            direction_dataset.close()
            raise
        if self._speed_dataset is not None:
            self._speed_dataset.close()
        if self._direction_dataset is not None:
            self._direction_dataset.close()
        self._speed_dataset = speed_dataset
        self._direction_dataset = direction_dataset
        self._active_month = month
        self._latitude = latitude
        self._longitude = longitude
        self._coarse_latitude = latitude[::_COARSE_STRIDE, ::_COARSE_STRIDE]
        self._coarse_longitude = longitude[::_COARSE_STRIDE, ::_COARSE_STRIDE]
        self._times = speed_time
        self._time_index = None
        self._speed_slice = None
        self._direction_slice = None
        self._slice_cache.clear()
        self._speed_name = speed_name
        self._direction_name = direction_name
        self._convention = convention

    def _load_slice(self, time_index: int) -> None:
        if self._time_index == time_index:
            return
        cached = self._slice_cache.pop(time_index, None)
        if cached is not None:
            self._speed_slice, self._direction_slice = cached
            self._slice_cache[time_index] = cached
            self._time_index = time_index
            return
        assert self._speed_dataset is not None and self._direction_dataset is not None
        speed = np.ma.asarray(self._speed_dataset.variables[self._speed_name][time_index, :, :], dtype=np.float64)
        direction = np.ma.asarray(
            self._direction_dataset.variables[self._direction_name][time_index, :, :],
            dtype=np.float64,
        )
        self._speed_slice = speed
        self._direction_slice = direction
        self._slice_cache[time_index] = (speed, direction)
        while len(self._slice_cache) > 2:
            self._slice_cache.popitem(last=False)
        self._time_index = time_index

    def _nearest_grid_point(self, latitude: float, longitude: float) -> tuple[int, int, float]:
        assert (
            self._latitude is not None
            and self._longitude is not None
            and self._coarse_latitude is not None
            and self._coarse_longitude is not None
        )
        coarse = _distance_squared(
            self._coarse_latitude,
            self._coarse_longitude,
            latitude,
            longitude,
        )
        if not np.isfinite(coarse).any():
            raise ValueError("CARRA2 coordinate grid contains no usable points.")
        coarse_row, coarse_column = np.unravel_index(np.nanargmin(coarse), coarse.shape)
        centre_row = coarse_row * _COARSE_STRIDE
        centre_column = coarse_column * _COARSE_STRIDE
        radius = _COARSE_STRIDE * 2
        row_start = max(0, centre_row - radius)
        row_stop = min(self._latitude.shape[0], centre_row + radius + 1)
        column_start = max(0, centre_column - radius)
        column_stop = min(self._latitude.shape[1], centre_column + radius + 1)
        local = _distance_squared(
            self._latitude[row_start:row_stop, column_start:column_stop],
            self._longitude[row_start:row_stop, column_start:column_stop],
            latitude,
            longitude,
        )
        local_row, local_column = np.unravel_index(np.nanargmin(local), local.shape)
        return (
            row_start + int(local_row),
            column_start + int(local_column),
            float(np.sqrt(local[local_row, local_column])),
        )


def _resolve_variables(speed: Dataset, direction: Dataset) -> tuple[str, str, str]:
    speed_name = next((name for name in ("si10", "u10") if name in speed.variables), None)
    direction_name = next((name for name in ("wdir10", "v10") if name in direction.variables), None)
    if speed_name is None or direction_name is None:
        raise ValueError("CARRA2 files require si10/wdir10 or u10/v10.")
    convention = "uv" if speed_name == "u10" else "speed_direction"
    return speed_name, direction_name, convention


def _wind_components(
    speed_value,
    direction_value,
    convention: str,
) -> tuple[float, float, float, float]:
    if np.ma.is_masked(speed_value) or np.ma.is_masked(direction_value):
        raise ValueError("CARRA2 wind sample is missing.")
    first = float(speed_value)
    second = float(direction_value)
    if not np.isfinite(first) or not np.isfinite(second):
        raise ValueError("CARRA2 wind sample is non-finite.")
    if convention == "uv":
        u, v = first, second
        speed = hypot(u, v)
        direction_from = (degrees(atan2(-u, -v)) + 360.0) % 360.0
        return speed, direction_from, u, v

    speed = first
    direction_from = second % 360.0
    # wdir10 is meteorological FROM; u/v point toward.
    radians_direction = radians(direction_from)
    u = -speed * sin(radians_direction)
    v = -speed * cos(radians_direction)
    computed_speed = hypot(u, v)
    computed_from = (degrees(atan2(-u, -v)) + 360.0) % 360.0
    return computed_speed, computed_from, u, v


def _distance_squared(
    grid_latitude: np.ndarray,
    grid_longitude: np.ndarray,
    latitude: float,
    longitude: float,
) -> np.ndarray:
    longitude_delta = (grid_longitude - longitude + 180.0) % 360.0 - 180.0
    return (grid_latitude - latitude) ** 2 + (longitude_delta * cos(radians(latitude))) ** 2


def _read_times(dataset: Dataset) -> list[datetime]:
    variable = dataset.variables.get("valid_time")
    if variable is None:
        variable = dataset.variables.get("time")
    if variable is None or not hasattr(variable, "units"):
        raise ValueError("CARRA2 file has no valid_time/time with CF units.")
    values = num2date(
        variable[:],
        units=variable.units,
        calendar=getattr(variable, "calendar", "standard"),
        only_use_cftime_datetimes=False,
    )
    return [_as_utc(value) for value in np.atleast_1d(values)]


def _file_month(path: Path) -> datetime | None:
    suffix = path.stem.rsplit("_", 1)[-1]
    try:
        return datetime.strptime(suffix, "%Y%m").replace(tzinfo=UTC)
    except ValueError:
        return None


def _unavailable(
    requested_time: datetime,
    reason: str,
    match: TimeMatchInfo | None = None,
) -> ProviderSample:
    return ProviderSample(
        available=False,
        source="CARRA2",
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
