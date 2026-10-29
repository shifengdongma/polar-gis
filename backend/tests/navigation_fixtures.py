"""Tiny synthetic NetCDF fixtures for navigation provider tests.

These files are explicitly marked synthetic via ``navigation_manifest.json`` in
the service tests; they never represent real environmental observations.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
from netCDF4 import Dataset


def _time_units(reference: datetime = datetime(2025, 2, 15, 0, 0, 0)) -> tuple[str, np.ndarray]:
    return "hours since 2025-02-15 00:00:00", None  # type: ignore[return-value]


def write_gebco(path: Path, latitude: np.ndarray, longitude: np.ndarray, elevation: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with Dataset(path, "w") as dataset:
        dataset.createDimension("lat", latitude.size)
        dataset.createDimension("lon", longitude.size)
        lat = dataset.createVariable("latitude", "f8", ("lat",))
        lon = dataset.createVariable("longitude", "f8", ("lon",))
        z = dataset.createVariable("elevation", "f8", ("lat", "lon"))
        lat[:] = latitude
        lon[:] = longitude
        z[:] = elevation
        z.units = "m"
        z.standard_name = "height_above_mean_sea_level"
    return path


def write_nextsim(
    path: Path,
    latitude: np.ndarray,
    longitude: np.ndarray,
    times_hours: list[float],
    concentration: np.ndarray,
    thickness: np.ndarray | None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with Dataset(path, "w") as dataset:
        dataset.createDimension("time", len(times_hours))
        dataset.createDimension("latitude", latitude.size)
        dataset.createDimension("longitude", longitude.size)
        time = dataset.createVariable("time", "f8", ("time",))
        time.units = "hours since 2025-02-15 00:00:00"
        time[:] = np.asarray(times_hours, dtype=np.float64)
        lat = dataset.createVariable("latitude", "f8", ("latitude",))
        lon = dataset.createVariable("longitude", "f8", ("longitude",))
        lat[:] = latitude
        lon[:] = longitude
        sic = dataset.createVariable("siconc", "f8", ("time", "latitude", "longitude"))
        sic.units = "1"
        sic[:] = concentration
        if thickness is not None:
            sit = dataset.createVariable("sithick", "f8", ("time", "latitude", "longitude"))
            sit.units = "m"
            sit[:] = thickness
    return path


def write_carra2_month(
    root: Path,
    month: str,
    latitude: np.ndarray,
    longitude: np.ndarray,
    times_hours: list[float],
    speed: np.ndarray,
    direction: np.ndarray,
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    speed_path = root / f"10m_wind_speed_{month}.nc"
    direction_path = root / f"10m_wind_direction_{month}.nc"
    for path, name, values, units in (
        (speed_path, "si10", speed, "m s-1"),
        (direction_path, "wdir10", direction, "degree"),
    ):
        with Dataset(path, "w") as dataset:
            dataset.createDimension("valid_time", len(times_hours))
            dataset.createDimension("latitude", latitude.shape[0])
            dataset.createDimension("longitude", latitude.shape[1])
            time = dataset.createVariable("valid_time", "f8", ("valid_time",))
            time.units = "hours since 2025-02-15 00:00:00"
            time[:] = np.asarray(times_hours, dtype=np.float64)
            lat = dataset.createVariable("latitude", "f8", ("latitude", "longitude"))
            lon = dataset.createVariable("longitude", "f8", ("latitude", "longitude"))
            lat[:] = latitude
            lon[:] = longitude
            variable = dataset.createVariable(name, "f8", ("valid_time", "latitude", "longitude"))
            variable.units = units
            variable[:] = values
    return speed_path, direction_path


def write_topaz(
    path: Path,
    x: np.ndarray,
    y: np.ndarray,
    times_hours: list[float],
    vxo: np.ndarray,
    vyo: np.ndarray,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with Dataset(path, "w") as dataset:
        dataset.createDimension("time", len(times_hours))
        dataset.createDimension("y", y.size)
        dataset.createDimension("x", x.size)
        time = dataset.createVariable("time", "f8", ("time",))
        time.units = "hours since 2025-02-15 00:00:00"
        time[:] = np.asarray(times_hours, dtype=np.float64)
        xv = dataset.createVariable("x", "f8", ("x",))
        yv = dataset.createVariable("y", "f8", ("y",))
        xv[:] = x
        yv[:] = y
        u = dataset.createVariable("vxo", "f8", ("time", "y", "x"))
        v = dataset.createVariable("vyo", "f8", ("time", "y", "x"))
        u.units = "m/s"
        v.units = "m/s"
        u[:] = vxo
        v[:] = vyo
    return path


def write_wam(
    path: Path,
    latitude: np.ndarray,
    longitude: np.ndarray,
    times_hours: list[float],
    height: np.ndarray,
    period: np.ndarray,
    direction: np.ndarray,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with Dataset(path, "w") as dataset:
        dataset.createDimension("time", len(times_hours))
        dataset.createDimension("latitude", latitude.size)
        dataset.createDimension("longitude", longitude.size)
        time = dataset.createVariable("time", "f8", ("time",))
        time.units = "hours since 2025-02-15 00:00:00"
        time[:] = np.asarray(times_hours, dtype=np.float64)
        lat = dataset.createVariable("latitude", "f8", ("latitude",))
        lon = dataset.createVariable("longitude", "f8", ("longitude",))
        lat[:] = latitude
        lon[:] = longitude
        for name, values, units in (
            ("VHM0", height, "m"),
            ("VTPK", period, "s"),
            ("VMDR", direction, "degree"),
        ):
            variable = dataset.createVariable(name, "f8", ("time", "latitude", "longitude"))
            variable.units = units
            variable[:] = values
    return path


def write_manifest(root: Path, fields: list[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "navigation_manifest.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "fields": {
                    field: {"quality": "synthetic", "source": "synthetic-fixture"}
                    for field in fields
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def full_fixture_tree(root: Path) -> None:
    """Create a tiny but format-correct synthetic tree for all five fields."""
    lat = np.array([74.0, 75.0, 76.0, 77.0], dtype=np.float64)
    lon = np.array([119.0, 120.0, 121.0, 122.0], dtype=np.float64)
    elevation = np.array(
        [
            [-1000.0, -2000.0, -3000.0, -4000.0],
            [-1200.0, -1500.0, -2500.0, -3500.0],
            [-900.0, -1200.0, -1800.0, -2800.0],
            [10.0, -800.0, -1500.0, -2200.0],
        ],
        dtype=np.float64,
    )
    write_gebco(root / "bathymetry" / "GEBCO_synthetic.nc", lat, lon, elevation)

    times = [0.0, 12.0, 24.0]
    concentration = np.array(
        [
            [[0.0, 0.2, 0.4, 0.6], [0.1, 0.3, 0.5, 0.7], [0.2, 0.4, 0.6, 0.8], [0.3, 0.5, 0.7, 0.9]],
            [[0.1, 0.3, 0.5, 0.7], [0.2, 0.4, 0.6, 0.8], [0.3, 0.5, 0.7, 0.9], [0.4, 0.6, 0.8, 1.0]],
            [[0.2, 0.4, 0.6, 0.8], [0.3, 0.5, 0.7, 0.9], [0.4, 0.6, 0.8, 1.0], [0.5, 0.7, 0.9, 1.0]],
        ],
        dtype=np.float64,
    )
    thickness = np.full_like(concentration, 1.2)
    write_nextsim(
        root / "ice" / "arctic_ice_20250215.nc",
        lat,
        lon,
        times,
        concentration,
        thickness,
    )

    wind_lat, wind_lon = np.meshgrid(lat, lon, indexing="ij")
    speed = np.full((3, 4, 4), 10.0)
    direction = np.full((3, 4, 4), 270.0)
    write_carra2_month(
        root / "wind",
        "202502",
        wind_lat,
        wind_lon,
        times,
        speed,
        direction,
    )

    # A small native TOPAZ grid around the same area.  x/y are in 100 km units.
    from pyproj import CRS, Transformer

    topaz_crs = CRS.from_proj4(
        "+proj=stere +lat_0=90 +lon_0=-45 +k=1 +R=6378273 +units=m +no_defs"
    )
    transformer = Transformer.from_crs("EPSG:4326", topaz_crs, always_xy=True)
    x0, y0 = transformer.transform(121.0, 75.5)
    x = (x0 + np.array([-200_000.0, 0.0, 200_000.0])) / 100_000.0
    y = (y0 + np.array([-200_000.0, 0.0, 200_000.0])) / 100_000.0
    vxo = np.full((3, 3, 3), 0.2)
    vyo = np.full((3, 3, 3), -0.1)
    write_topaz(root / "current" / "Copernicus_current_20250215.nc", x, y, times, vxo, vyo)

    height = np.full((3, 4, 4), 2.0)
    period = np.full((3, 4, 4), 7.0)
    wave_direction = np.full((3, 4, 4), 240.0)
    write_wam(
        root / "wave" / "Copernicus_wave_20250215.nc",
        lat,
        lon,
        times,
        height,
        period,
        wave_direction,
    )
    write_manifest(root, ["bathymetry", "ice", "wind", "current", "wave"])
