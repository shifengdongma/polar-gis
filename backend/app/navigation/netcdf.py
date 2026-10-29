"""NetCDF opening helper that does not mutate the process working directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from netCDF4 import Dataset


def open_netcdf(path: str | Path, mode: str = "r", **kwargs: Any) -> Dataset:
    """Open a NetCDF file by absolute path.

    The reference project changed the process CWD for non-ASCII Windows paths;
    that is not concurrency-safe.  netCDF4 accepts Unicode paths on modern
    Windows builds, so keep the operation local and side-effect free.
    """
    return Dataset(str(Path(path).resolve()), mode=mode, **kwargs)
