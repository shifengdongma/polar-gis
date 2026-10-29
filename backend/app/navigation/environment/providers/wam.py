"""WAM wave provider: significant height, peak period, mean direction FROM."""

from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime
from math import atan2, degrees, hypot
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


class WAMWaveProvider(BaseEnvironmentProvider):
    field = "wave"
    source_name = "Arctic WAM"

    def __init__(self, data_root: Path, manifest: EnvironmentManifest) -> None:
        self.data_root = Path(data_root)
        self.manifest = manifest
        search_root = self.data_root / "wave" if (self.data_root / "wave").is_dir() else self.data_root
        pattern = manifest.field("wave").glob or "Copernicus_wave_*.nc"
        paths = sorted(search_root.glob(pattern)) if search_root.is_dir() else []
        self._paths_by_date = {
            parsed: path for path in paths if (parsed := _file_date(path)) is not None
        }
        self._lock = RLock()
        self._dataset: Dataset | None = None
        self._active_path: Path | None = None
        self._latitude: np.ndarray | None = None
        self._longitude: np.ndarray | None = None
        self._times: list[datetime] = []
        self._issue_time: datetime | None = None
        self._time_index: int | None = None
        self._slices: dict[str, np.ma.MaskedArray] = {}
        self._slice_cache: OrderedDict[int, dict[str, np.ma.MaskedArray]] = OrderedDict()
        # Grid metadata is constant for a file; computing nanmin/nanmax for
        # every sample made full-grid planning unnecessarily slow.
        self._coverage: dict[str, float] | None = None

    def available(self) -> bool:
        return bool(self._paths_by_date)

    def times(self) -> list[datetime]:
        return sorted(self._paths_by_date)

    def coverage(self) -> dict[str, float] | None:
        if not self.available():
            return None
        with self._lock:
            if self._coverage is None:
                try:
                    self._activate(next(iter(self._paths_by_date.values())))
                    assert self._latitude is not None and self._longitude is not None
                    self._coverage = {
                        "minLatitude": float(np.nanmin(self._latitude)),
                        "maxLatitude": float(np.nanmax(self._latitude)),
                        "minLongitude": float(np.nanmin(self._longitude)),
                        "maxLongitude": float(np.nanmax(self._longitude)),
                    }
                except Exception:  # noqa: BLE001
                    return None
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
        requested = _utc(requested_time)
        if not self.available():
            return _unavailable(requested, "wave_file_missing")
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
                        selection.reason or "wave_time_unavailable",
                        selection.match_info(),
                    )
                self._load_slice(selection.index)
                assert self._latitude is not None and self._longitude is not None
                row0, row1, dy = _bracket(self._latitude, latitude)
                column0, column1, dx = _bracket(self._longitude, longitude)
                height = _linear_sample(
                    self._slices["height"], row0, row1, column0, column1, dy, dx
                )
                period = _linear_sample(
                    self._slices["period"], row0, row1, column0, column1, dy, dx
                )
                direction = _circular_sample(
                    self._slices["direction"], row0, row1, column0, column1, dy, dx
                )
                return ProviderSample(
                    available=True,
                    values={
                        "heightM": height,
                        "periodS": period,
                        "directionFromDeg": direction,
                    },
                    units={
                        "heightM": "m",
                        "periodS": "s",
                        "directionFromDeg": "degree",
                    },
                    component_quality={
                        "heightM": DataQuality.REAL,
                        "periodS": DataQuality.REAL,
                        "directionFromDeg": DataQuality.REAL,
                    },
                    source=self.source_name,
                    time=selection.match_info(),
                    coverage=self._coverage,
                )
        except Exception as error:  # noqa: BLE001
            return _unavailable(
                requested,
                f"wave_read_error:{type(error).__name__}",
                selection.match_info() if selection is not None and selection.matched_time else None,
            )

    def close(self) -> None:
        with self._lock:
            if self._dataset is not None:
                self._dataset.close()
            self._dataset = None
            self._active_path = None
            self._latitude = None
            self._longitude = None
            self._times = []
            self._time_index = None
            self._slices = {}
            self._slice_cache.clear()
            self._coverage = None

    def _activate(self, path: Path) -> None:
        if self._active_path == path and self._dataset is not None:
            return
        dataset = open_netcdf(path)
        try:
            missing = {"time", "latitude", "longitude", "VHM0", "VTPK", "VMDR"}.difference(
                dataset.variables
            )
            if missing:
                raise ValueError(f"WAM file is missing: {', '.join(sorted(missing))}")
            latitude = np.asarray(dataset.variables["latitude"][:], dtype=np.float64)
            longitude = np.asarray(dataset.variables["longitude"][:], dtype=np.float64)
            if latitude.ndim != 1 or longitude.ndim != 1:
                raise ValueError("WAM latitude/longitude must be one-dimensional.")
            times = _read_times(dataset)
        except Exception:
            dataset.close()
            raise
        if self._dataset is not None:
            self._dataset.close()
        self._dataset = dataset
        self._active_path = path
        self._latitude = latitude
        self._longitude = longitude
        self._times = times
        self._issue_time = _read_issue_time(dataset)
        self._time_index = None
        self._slices = {}
        self._slice_cache.clear()
        self._coverage = None

    def _load_slice(self, time_index: int) -> None:
        if self._time_index == time_index:
            return
        cached = self._slice_cache.pop(time_index, None)
        if cached is not None:
            self._slices = cached
            self._slice_cache[time_index] = cached
            self._time_index = time_index
            return
        assert self._dataset is not None
        self._slices = {
            "height": _scaled_slice(self._dataset.variables["VHM0"], time_index, "height"),
            "period": _scaled_slice(self._dataset.variables["VTPK"], time_index, "period"),
            "direction": np.ma.masked_invalid(
                np.ma.asarray(self._dataset.variables["VMDR"][time_index, :, :], dtype=np.float64)
            ),
        }
        self._slice_cache[time_index] = self._slices
        while len(self._slice_cache) > 3:
            self._slice_cache.popitem(last=False)
        self._time_index = time_index


def _scaled_slice(variable, time_index: int, kind: str) -> np.ma.MaskedArray:
    values = np.ma.masked_invalid(np.ma.asarray(variable[time_index, :, :], dtype=np.float64))
    units = str(getattr(variable, "units", "")).strip().casefold()
    if kind == "height" and units in {"cm", "centimeter", "centimeters"}:
        return values * 0.01
    return values


def _bracket(axis: np.ndarray, value: float) -> tuple[int, int, float]:
    minimum, maximum = float(np.min(axis)), float(np.max(axis))
    if value < minimum or value > maximum:
        raise ValueError("Point is outside wave coverage.")
    ascending = axis[0] < axis[-1]
    ordered = axis if ascending else axis[::-1]
    upper_ordered = min(max(int(np.searchsorted(ordered, value, side="right")), 1), len(axis) - 1)
    lower_ordered = upper_ordered - 1
    lower = lower_ordered if ascending else len(axis) - 1 - lower_ordered
    upper = upper_ordered if ascending else len(axis) - 1 - upper_ordered
    denominator = float(axis[upper] - axis[lower])
    fraction = 0.0 if denominator == 0 else (value - float(axis[lower])) / denominator
    return lower, upper, float(fraction)


def _weights(dy: float, dx: float) -> np.ndarray:
    return np.array([(1 - dy) * (1 - dx), (1 - dy) * dx, dy * (1 - dx), dy * dx], dtype=np.float64)


def _valid_corners(values, row0: int, row1: int, column0: int, column1: int) -> np.ndarray:
    corners = np.ma.asarray(values[[row0, row0, row1, row1], [column0, column1, column0, column1]])
    raw = np.asarray(corners.filled(np.nan), dtype=np.float64)
    if np.any(np.ma.getmaskarray(corners)) or not np.all(np.isfinite(raw)):
        raise ValueError("No wave data at requested location.")
    return raw


def _linear_sample(values, row0, row1, column0, column1, dy, dx) -> float:
    return float(np.dot(_valid_corners(values, row0, row1, column0, column1), _weights(dy, dx)))


def _circular_sample(values, row0, row1, column0, column1, dy, dx) -> float:
    angles = np.deg2rad(_valid_corners(values, row0, row1, column0, column1))
    weights = _weights(dy, dx)
    x = float(np.dot(np.cos(angles), weights))
    y = float(np.dot(np.sin(angles), weights))
    if hypot(x, y) < 1e-10:
        raise ValueError("Wave direction is undefined at requested location.")
    return (degrees(atan2(y, x)) + 360.0) % 360.0


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
        source="Arctic WAM",
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
