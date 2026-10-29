"""Sea-ice provider with explicit Polar-GIS and neXtSIM backends.

The existing Polar-GIS ``IceService`` remains the authority for the ice layer
(PNG tiles, timeline, hover).  This adapter only reads its raw concentration
values for environment/risk/planning and never modifies that service.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from netCDF4 import Dataset, num2date
from pyproj import Transformer

from app.navigation.contracts import DataQuality, TimeMatchInfo
from app.navigation.environment.manifest import EnvironmentManifest
from app.navigation.environment.models import ProviderSample
from app.navigation.environment.providers.base import BaseEnvironmentProvider
from app.navigation.environment.time_manager import select_time
from app.navigation.netcdf import open_netcdf
from app.services.ice import IceService, shared_ice_service


class IceProvider(BaseEnvironmentProvider):
    field = "ice"
    source_name = "Polar-GIS Ice / neXtSIM-F"

    def __init__(
        self,
        navigation_ice_root: Path,
        polar_gis_ice_root: Path,
        manifest: EnvironmentManifest,
        *,
        backend: str = "auto",
        tile_cache_entries: int = 64,
        max_zoom: int = 10,
    ) -> None:
        self.navigation_ice_root = Path(navigation_ice_root)
        self.polar_gis_ice_root = Path(polar_gis_ice_root)
        self.manifest = manifest
        self._backend = self._choose_backend(backend)
        self._ice_service: IceService | None = None
        self._nextsim: _NextsimBackend | None = None
        # A Transformer is expensive to build; grid sampling must reuse it.
        self._to_polar = Transformer.from_crs("EPSG:4326", "EPSG:3413", always_xy=True)
        # IceService.info() scans NetCDF metadata for every date.  Sampling
        # thousands of planning cells must not repeat that scan per point.
        self._info_cache: tuple[float, dict] | None = None
        if self._backend == "polar_gis":
            # Share the exact instance used by /api/v1/ice: one metadata scan,
            # one warm-up thread and one 26M-cell grid cache per process.
            self._ice_service = shared_ice_service(
                self.polar_gis_ice_root,
                tile_cache_entries=tile_cache_entries,
                max_zoom=max_zoom,
            )
        elif self._backend == "nextsim":
            self._nextsim = _NextsimBackend(self.navigation_ice_root)

    def _choose_backend(self, requested: str) -> str:
        if requested in {"polar_gis", "nextsim"}:
            return requested
        navigation_files = sorted(self.navigation_ice_root.glob("*.nc")) if self.navigation_ice_root.is_dir() else []
        polar_files = sorted(self.polar_gis_ice_root.glob("*.nc")) if self.polar_gis_ice_root.is_dir() else []
        if navigation_files and self.navigation_ice_root.resolve() != self.polar_gis_ice_root.resolve():
            return "nextsim"
        if polar_files or navigation_files:
            return "polar_gis"
        return "unavailable"

    def available(self) -> bool:
        if self._backend == "polar_gis":
            info = self._polar_info()
            return bool(info.get("dates")) and any(
                field.get("id") == "concentration" for field in info.get("fields", [])
            )
        if self._backend == "nextsim":
            return self._nextsim is not None and self._nextsim.available()
        return False

    def times(self) -> list[datetime]:
        if self._backend == "polar_gis":
            return [_parse_day(day) for day in self._service().dates]
        if self._backend == "nextsim":
            return self._nextsim.times() if self._nextsim is not None else []
        return []

    def coverage(self) -> dict[str, float] | None:
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
        if self._backend == "polar_gis":
            return self._sample_polar_gis(longitude, latitude, requested_time, max_lag_hours, allow_future)
        if self._backend == "nextsim" and self._nextsim is not None:
            return self._nextsim.sample(longitude, latitude, requested_time, max_lag_hours, allow_future)
        return _unavailable(requested_time, "ice_data_missing")

    def _polar_info(self) -> dict:
        """Cache the directory metadata scan for a short period.

        During one planning run the same provider samples ~15k points; calling
        ``IceService.info()`` (which re-scans every date) once per point made
        the ice field the slowest part of grid construction.
        """
        now = time.monotonic()
        if self._info_cache is not None and now - self._info_cache[0] < 60.0:
            return self._info_cache[1]
        info = self._service().info()
        self._info_cache = (now, info)
        return info

    def _sample_polar_gis(
        self,
        longitude: float,
        latitude: float,
        requested_time: datetime,
        max_lag_hours: float | None,
        allow_future: bool,
    ) -> ProviderSample:
        service = self._service()
        info = self._polar_info()
        dates = [_parse_day(day) for day in info.get("dates", [])]
        selection = select_time(
            dates,
            requested_time,
            max_lag_hours=max_lag_hours,
            allow_future=allow_future,
        )
        if not selection.available or selection.index is None:
            return _unavailable(requested_time, selection.reason or "ice_time_unavailable", selection.match_info())
        day = info["dates"][selection.index]
        x, y = self._to_polar.transform(longitude, latitude)
        concentration = service.value_at(day, x, y, "EPSG:3413", "concentration")
        thickness = service.value_at(day, x, y, "EPSG:3413", "thickness")
        values: dict[str, float | bool | None] = {}
        qualities: dict[str, DataQuality] = {}
        units: dict[str, str] = {}
        if concentration is not None:
            raw = float(concentration["value"])
            values["concentration"] = _normalise_concentration(raw)
            units["concentration"] = "1"
            qualities["concentration"] = DataQuality.REAL
        else:
            values["concentration"] = None
            qualities["concentration"] = DataQuality.MISSING
            units["concentration"] = "1"
        if thickness is not None:
            values["thicknessM"] = float(thickness["value"])
            units["thicknessM"] = "m"
            qualities["thicknessM"] = DataQuality.REAL
        else:
            values["thicknessM"] = None
            qualities["thicknessM"] = DataQuality.MISSING
            units["thicknessM"] = "m"
        available = values["concentration"] is not None
        reason = None if values["thicknessM"] is not None else "ice_thickness_unavailable"
        return ProviderSample(
            available=available,
            values=values,
            units=units,
            component_quality=qualities,
            source="polar-gis-ice",
            time=selection.match_info(),
            reason=reason,
        )

    def _service(self) -> IceService:
        assert self._ice_service is not None
        return self._ice_service

    def close(self) -> None:
        self._info_cache = None
        if self._nextsim is not None:
            self._nextsim.close()


def _unavailable(
    requested_time: datetime,
    reason: str,
    match: TimeMatchInfo | None = None,
) -> ProviderSample:
    return ProviderSample(
        available=False,
        source="ice",
        time=match or TimeMatchInfo(requested_time=requested_time),
        reason=reason,
    )


def _parse_day(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)


def _normalise_concentration(value: float) -> float:
    numeric = float(value)
    return max(0.0, min(1.0, numeric / 100.0 if numeric > 1.0 else numeric))


class _NextsimBackend:
    """Minimal neXtSIM-F reader for point sampling.

    Files are expected to be daily ``*_YYYYMMDD.nc`` with 1-D latitude/
    longitude and time-varying ``siconc``/``sithick``.  A missing thickness
    variable is a missing component, not a reason to drop concentration.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._files: dict[datetime, Path] = {}
        for path in sorted(root.glob("*.nc")) if root.is_dir() else []:
            parsed = _file_date(path)
            if parsed is not None:
                self._files[parsed] = path
        self._dataset: Dataset | None = None
        self._active_path: Path | None = None
        self._latitude: np.ndarray | None = None
        self._longitude: np.ndarray | None = None
        self._times: list[datetime] = []
        self._siconc: np.ma.MaskedArray | None = None
        self._sithick: np.ma.MaskedArray | None = None
        self._time_index: int | None = None

    def available(self) -> bool:
        return bool(self._files)

    def times(self) -> list[datetime]:
        return sorted(self._files)

    def sample(
        self,
        longitude: float,
        latitude: float,
        requested_time: datetime,
        max_lag_hours: float | None,
        allow_future: bool,
    ) -> ProviderSample:
        if not self._files:
            return _unavailable(requested_time, "ice_data_missing")
        dates = list(self._files)
        selection = select_time(dates, requested_time, max_lag_hours=max_lag_hours, allow_future=allow_future)
        if not selection.available or selection.index is None:
            return _unavailable(requested_time, selection.reason or "ice_time_unavailable", selection.match_info())
        path = self._files[dates[selection.index]]
        time_selection = None
        try:
            self._activate(path)
            assert self._latitude is not None and self._longitude is not None
            time_selection = select_time(
                self._times,
                requested_time,
                max_lag_hours=max_lag_hours,
                allow_future=allow_future,
            )
            if not time_selection.available or time_selection.index is None:
                return _unavailable(
                    requested_time,
                    time_selection.reason or "ice_time_unavailable",
                    time_selection.match_info(),
                )
            self._load_slice(time_selection.index)
            row = _nearest_index(self._latitude, latitude)
            column = _nearest_index(self._longitude, _wrap_longitude(longitude, self._longitude))
            if row is None or column is None:
                return _unavailable(
                    requested_time,
                    "out_of_coverage",
                    time_selection.match_info(),
                )
            assert self._siconc is not None
            concentration = _masked_value(self._siconc, row, column)
            thickness = (
                _masked_value(self._sithick, row, column)
                if self._sithick is not None
                else None
            )
            values: dict[str, float | bool | None] = {
                "concentration": None if concentration is None else _normalise_concentration(concentration),
                "thicknessM": thickness,
            }
            qualities = {
                "concentration": DataQuality.REAL if concentration is not None else DataQuality.MISSING,
                "thicknessM": DataQuality.REAL if thickness is not None else DataQuality.MISSING,
            }
            return ProviderSample(
                available=concentration is not None,
                values=values,
                units={"concentration": "1", "thicknessM": "m"},
                component_quality=qualities,
                source="neXtSIM-F",
                time=time_selection.match_info(),
                reason=None if thickness is not None else "ice_thickness_unavailable",
            )
        except Exception as error:  # noqa: BLE001
            return _unavailable(
                requested_time,
                f"ice_read_error:{type(error).__name__}",
                time_selection.match_info()
                if time_selection is not None and time_selection.matched_time
                else None,
            )

    def _activate(self, path: Path) -> None:
        if self._active_path == path and self._dataset is not None:
            return
        self.close()
        dataset = open_netcdf(path)
        try:
            lat_name, lon_name = _find_lat_lon(dataset)
            self._latitude = np.asarray(dataset.variables[lat_name][:], dtype=np.float64)
            self._longitude = np.asarray(dataset.variables[lon_name][:], dtype=np.float64)
            if self._latitude.ndim != 1 or self._longitude.ndim != 1:
                raise ValueError("neXtSIM latitude/longitude must be one-dimensional.")
            time_variable = dataset.variables.get("time")
            if time_variable is None:
                raise ValueError("neXtSIM file has no time variable.")
            values = num2date(
                time_variable[:],
                units=time_variable.units,
                calendar=getattr(time_variable, "calendar", "standard"),
                only_use_cftime_datetimes=False,
            )
            self._times = [_as_utc(value) for value in np.atleast_1d(values)]
            self._siconc = None
            self._sithick = None
            self._dataset = dataset
            self._active_path = path
            self._time_index = None
        except Exception:
            dataset.close()
            raise

    def _load_slice(self, time_index: int) -> None:
        if self._time_index == time_index:
            return
        assert self._dataset is not None
        concentration = _surface_slice(self._dataset.variables["siconc"], time_index)
        thickness = (
            _surface_slice(self._dataset.variables["sithick"], time_index)
            if "sithick" in self._dataset.variables
            else None
        )
        if self._latitude is not None and self._longitude is not None:
            expected = (self._latitude.size, self._longitude.size)
            if concentration.shape == (expected[1], expected[0]):
                concentration = concentration.T
                if thickness is not None:
                    thickness = thickness.T
            if concentration.shape != expected:
                raise ValueError("neXtSIM concentration dimensions do not match latitude/longitude.")
        self._siconc = concentration
        self._sithick = thickness
        self._time_index = time_index

    def close(self) -> None:
        if self._dataset is not None:
            self._dataset.close()
        self._dataset = None
        self._active_path = None
        self._latitude = None
        self._longitude = None
        self._times = []
        self._siconc = None
        self._sithick = None
        self._time_index = None


def _find_lat_lon(dataset: Dataset) -> tuple[str, str]:
    by_case = {name.casefold(): name for name in dataset.variables}
    lat = next((by_case[name] for name in ("latitude", "lat") if name in by_case), None)
    lon = next((by_case[name] for name in ("longitude", "lon") if name in by_case), None)
    if lat is None or lon is None:
        raise ValueError("neXtSIM file has no latitude/longitude.")
    return lat, lon


def _surface_slice(variable, time_index: int) -> np.ma.MaskedArray:
    dimensions = variable.dimensions
    time_axis = next((i for i, name in enumerate(dimensions) if name.casefold() == "time"), None)
    if time_axis is None:
        raise ValueError("neXtSIM variable has no time dimension.")
    selection = [slice(None)] * variable.ndim
    selection[time_axis] = time_index
    depth_axis = next(
        (i for i, name in enumerate(dimensions) if name.casefold() in {"depth", "lev", "level"}),
        None,
    )
    if depth_axis is not None:
        selection[depth_axis] = 0
    data = np.ma.asarray(variable[tuple(selection)], dtype=np.float64)
    if data.ndim != 2:
        raise ValueError("neXtSIM surface variable must be two-dimensional after time selection.")
    return data


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


def _wrap_longitude(value: float, axis: np.ndarray) -> float:
    low, high = float(np.min(axis)), float(np.max(axis))
    if low >= 0.0 and high > 180.0:
        return value % 360.0
    if low < 0.0 and high <= 180.0:
        return (value + 180.0) % 360.0 - 180.0
    return value


def _masked_value(values: np.ma.MaskedArray, row: int, column: int) -> float | None:
    raw = values[row, column]
    if np.ma.is_masked(raw):
        return None
    numeric = float(raw)
    return numeric if np.isfinite(numeric) else None


def _file_date(path: Path) -> datetime | None:
    stem = path.stem
    digits = "".join(ch for ch in stem if ch.isdigit())
    for length in (8,):
        if len(digits) >= length:
            try:
                return datetime.strptime(digits[-length:], "%Y%m%d").replace(tzinfo=UTC)
            except ValueError:
                continue
    return None


def _as_utc(value) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return datetime(
        value.year, value.month, value.day, getattr(value, "hour", 0), getattr(value, "minute", 0), getattr(value, "second", 0), tzinfo=UTC
    )
