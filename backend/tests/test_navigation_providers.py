"""Provider and environment-service tests on synthetic NetCDF fixtures."""

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from navigation_fixtures import (
    full_fixture_tree,
    write_manifest,
    write_nextsim,
)

from app.core.config import Settings
from app.navigation.contracts import DataQuality
from app.navigation.environment.manifest import load_manifest
from app.navigation.environment.providers.carra2 import CARRA2WindProvider
from app.navigation.environment.providers.gebco import GEBCOBathymetryProvider
from app.navigation.environment.providers.ice import IceProvider
from app.navigation.environment.providers.topaz5 import TOPAZ5CurrentProvider
from app.navigation.environment.providers.wam import WAMWaveProvider
from app.navigation.environment.service import EnvironmentService

REQUESTED = datetime(2025, 2, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "navigation"
    full_fixture_tree(root)
    return root


@pytest.fixture
def service(tmp_path: Path, fixture_root: Path) -> EnvironmentService:
    settings = Settings(
        navigation_data_root=fixture_root,
        navigation_ice_data_root=fixture_root / "ice",
        navigation_ice_backend="nextsim",
        navigation_manifest_path=fixture_root / "navigation_manifest.json",
        ice_data_root=tmp_path / "no-ice",
        planner_result_root=tmp_path / "plans",
    )
    return EnvironmentService(settings)


def test_gebco_water_land_and_coverage(fixture_root: Path) -> None:
    manifest = load_manifest(fixture_root / "navigation_manifest.json")
    provider = GEBCOBathymetryProvider(fixture_root, manifest)
    water = provider.sample(119.1, 74.1, REQUESTED, max_lag_hours=None, allow_future=False)
    assert water.available is True
    assert water.values["depthM"] == pytest.approx(1000.0)
    assert water.values["isLand"] is False

    land = provider.sample(119.1, 77.0, REQUESTED, max_lag_hours=None, allow_future=False)
    assert land.available is True
    assert land.values["isLand"] is True
    assert land.values["depthM"] == 0.0

    outside = provider.sample(140.0, 74.1, REQUESTED, max_lag_hours=None, allow_future=False)
    assert outside.available is False
    assert outside.reason == "out_of_coverage"
    provider.close()


def test_nextsim_ice_zero_concentration_is_valid(fixture_root: Path) -> None:
    manifest = load_manifest(fixture_root / "navigation_manifest.json")
    provider = IceProvider(
        fixture_root / "ice",
        fixture_root / "no-polar-ice",
        manifest,
        backend="nextsim",
    )
    sample = provider.sample(119.0, 74.0, datetime(2025, 2, 15, tzinfo=UTC), max_lag_hours=24, allow_future=False)
    assert sample.available is True
    assert sample.values["concentration"] == pytest.approx(0.0)
    assert sample.values["thicknessM"] == pytest.approx(1.2)
    assert sample.component_quality["thicknessM"] is DataQuality.REAL
    provider.close()


def test_nextsim_missing_thickness_keeps_concentration(tmp_path: Path) -> None:
    root = tmp_path / "ice"
    latitude = np.array([74.0, 75.0])
    longitude = np.array([119.0, 120.0])
    write_nextsim(
        root / "arctic_ice_20250215.nc",
        latitude,
        longitude,
        [0.0],
        np.array([[[0.4, 0.5], [0.6, 0.7]]]),
        None,
    )
    write_manifest(tmp_path, ["ice"])
    manifest = load_manifest(tmp_path / "navigation_manifest.json")
    provider = IceProvider(root, tmp_path / "no-polar-ice", manifest, backend="nextsim")
    sample = provider.sample(119.0, 74.0, datetime(2025, 2, 15, tzinfo=UTC), max_lag_hours=24, allow_future=False)
    assert sample.available is True
    assert sample.values["concentration"] == pytest.approx(0.4)
    assert sample.values["thicknessM"] is None
    assert sample.component_quality["thicknessM"] is DataQuality.MISSING
    assert sample.reason == "ice_thickness_unavailable"
    provider.close()


def test_carra2_wind_from_direction(fixture_root: Path) -> None:
    manifest = load_manifest(fixture_root / "navigation_manifest.json")
    provider = CARRA2WindProvider(fixture_root, manifest)
    sample = provider.sample(120.0, 75.0, REQUESTED, max_lag_hours=6, allow_future=False)
    assert sample.available is True
    assert sample.values["speedMs"] == pytest.approx(10.0)
    assert sample.values["directionFromDeg"] == pytest.approx(270.0)
    assert sample.values["uMs"] == pytest.approx(10.0, abs=1e-6)
    assert sample.values["vMs"] == pytest.approx(0.0, abs=1e-6)
    provider.close()


def test_topaz_current_is_rotated_to_east_north(fixture_root: Path) -> None:
    manifest = load_manifest(fixture_root / "navigation_manifest.json")
    provider = TOPAZ5CurrentProvider(fixture_root, manifest)
    sample = provider.sample(121.0, 75.5, REQUESTED, max_lag_hours=24, allow_future=False)
    assert sample.available is True, sample.reason
    assert sample.values["speedMs"] > 0.0
    assert sample.values["uMs"] is not None
    assert sample.values["vMs"] is not None
    assert sample.time.matched_time is not None
    provider.close()


def test_wam_wave_height_period_direction(fixture_root: Path) -> None:
    manifest = load_manifest(fixture_root / "navigation_manifest.json")
    provider = WAMWaveProvider(fixture_root, manifest)
    sample = provider.sample(120.0, 75.0, REQUESTED, max_lag_hours=24, allow_future=False)
    assert sample.available is True
    assert sample.values["heightM"] == pytest.approx(2.0)
    assert sample.values["periodS"] == pytest.approx(7.0)
    assert sample.values["directionFromDeg"] == pytest.approx(240.0)
    provider.close()


def test_real_only_rejects_synthetic_manifest(service: EnvironmentService) -> None:
    sample = service.query(120.0, 75.0, REQUESTED, ["bathymetry", "wind"], "real_only")
    assert sample.fields["bathymetry"].available is False
    assert sample.fields["bathymetry"].reason == "synthetic_data_not_allowed"
    assert sample.fields["wind"].available is False
    assert sample.quality_summary is DataQuality.MISSING


def test_allow_synthetic_research_accepts_marked_fixtures(service: EnvironmentService) -> None:
    sample = service.query(
        120.0,
        75.0,
        REQUESTED,
        ["bathymetry", "ice", "wind", "current", "wave"],
        "allow_synthetic_research",
    )
    assert sample.fields["bathymetry"].available is True
    assert sample.fields["bathymetry"].quality is DataQuality.SYNTHETIC
    assert sample.fields["wind"].available is True
    assert sample.fields["wind"].values["speedMs"] == pytest.approx(10.0)
    assert sample.fields["ice"].values["concentration"] is not None


def test_synthetic_query_fills_missing_fields_without_losing_bathy(tmp_path: Path) -> None:
    root = tmp_path / "navigation"
    from navigation_fixtures import write_gebco

    write_gebco(
        root / "bathymetry" / "GEBCO_synthetic.nc",
        np.array([74.0, 75.0]),
        np.array([119.0, 120.0]),
        np.array([[-100.0, -200.0], [-300.0, -400.0]]),
    )
    write_manifest(root, ["bathymetry"])
    settings = Settings(
        navigation_data_root=root,
        navigation_ice_data_root=tmp_path / "no-ice",
        navigation_ice_backend="nextsim",
        navigation_manifest_path=root / "navigation_manifest.json",
        ice_data_root=tmp_path / "no-ice",
        planner_result_root=tmp_path / "plans",
    )
    service = EnvironmentService(settings)
    sample = service.query(119.1, 74.1, REQUESTED, ["bathymetry", "wind", "wave"], "allow_synthetic_research")
    assert sample.fields["bathymetry"].available is True
    assert sample.fields["wind"].available is True
    assert sample.fields["wind"].quality is DataQuality.SYNTHETIC
    assert "synthetic-gap-fill" in (sample.fields["wind"].source or "")
    assert sample.fields["wave"].available is True
    assert sample.fields["wave"].values["heightM"] is not None


def test_field_vectors_and_snapshot(service: EnvironmentService) -> None:
    available, reason, times, points = service.field_vectors(
        "wind",
        (119.0, 74.0, 122.0, 77.0),
        REQUESTED,
        zoom=3,
        max_points=40,
        policy="allow_synthetic_research",
    )
    assert available is True, reason
    assert 4 <= len(points) <= 40
    assert points[0].available is True
    assert times

    snapshot = service.snapshot(REQUESTED, "allow_synthetic_research")
    assert snapshot.fields["bathymetry"].available is True
    assert snapshot.fields["wind"].matched_time is not None
    assert snapshot.fields["current"].matched_time is not None
    assert snapshot.fields["wave"].matched_time is not None
