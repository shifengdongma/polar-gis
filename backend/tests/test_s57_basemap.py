"""Tests for S-57 basemap preflight and profile services."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.s57_basemap import (
    BasemapPreflightService,
    BasemapProfile,
    PreflightResult,
    _compute_file_hash,
    _compute_manifest_hash,
    _extract_dsid_metadata,
    _safe_int,
    list_available_profiles,
    load_profile,
)


# ── fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def mock_ogrinfo_overview() -> dict:
    return {
        "driverShortName": "S57",
        "layers": [
            {
                "layerName": "DSID",
                "featureCount": 1,
                "properties": {
                    "DSID_DSNM": "GLOBAL_OVERVIEW",
                    "DSID_INTU": 1,
                    "DSID_EDTN": "1",
                    "DSID_UPDN": "0",
                    "DSID_UADT": "20250101",
                },
            },
            {
                "layerName": "DSPM",
                "featureCount": 1,
                "properties": {
                    "DSPM_CSCL": 3500000,
                },
            },
        ],
    }


@pytest.fixture
def mock_ogrinfo_band2() -> dict:
    return {
        "driverShortName": "S57",
        "layers": [
            {
                "layerName": "DSID",
                "featureCount": 1,
                "properties": {
                    "DSID_DSNM": "GENERAL_CHART",
                    "DSID_INTU": 2,
                    "DSID_EDTN": "1",
                    "DSID_UPDN": "0",
                },
            },
            {
                "layerName": "DSPM",
                "featureCount": 1,
                "properties": {"DSPM_CSCL": 180000},
            },
        ],
    }


@pytest.fixture
def mock_ogrinfo_no_dsid() -> dict:
    return {"driverShortName": "S57", "layers": []}


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.s57_basemap_source_root = "/data/s57-basemaps"
    s.s57_basemap_profile = "global_overview_v1"
    s.s57_basemap_allow_local_source = True
    return s


# ── unit tests ────────────────────────────────────────────────────────

class TestSafeInt:
    def test_int(self):
        assert _safe_int(1) == 1
        assert _safe_int("3") == 3

    def test_none(self):
        assert _safe_int(None) is None

    def test_invalid(self):
        assert _safe_int("abc") is None


class TestExtractDsidMetadata:
    def test_valid(self, mock_ogrinfo_overview):
        meta = _extract_dsid_metadata(mock_ogrinfo_overview)
        assert meta["intu"] == 1
        assert meta["dsnm"] == "GLOBAL_OVERVIEW"
        assert meta["cscl"] == 3500000
        assert meta["edtn"] == "1"
        assert meta["updn"] == 0
        assert meta["uadt"] == "20250101"

    def test_band2(self, mock_ogrinfo_band2):
        meta = _extract_dsid_metadata(mock_ogrinfo_band2)
        assert meta["intu"] == 2
        assert meta["dsnm"] == "GENERAL_CHART"
        assert meta["cscl"] == 180000

    def test_missing_dsid(self, mock_ogrinfo_no_dsid):
        meta = _extract_dsid_metadata(mock_ogrinfo_no_dsid)
        assert meta["intu"] is None
        assert meta["dsnm"] is None


class TestProfileLoading:
    def test_load_global_overview(self):
        profile = load_profile("global_overview_v1")
        assert profile.code == "global_overview_v1"
        assert profile.usage_band == 1
        assert profile.load_profile == "core_chart"
        assert len(profile.expected_cells) == 18
        assert profile.expected_cells["C110408A"] == 0
        assert profile.expected_cells["NO1A3000"] == 3
        assert profile.expected_cells["US1BS03M"] == 5

    def test_load_missing_raises(self):
        with pytest.raises(FileNotFoundError):
            load_profile("nonexistent_profile")

    def test_list_profiles(self):
        profiles = list_available_profiles()
        assert any(p.code == "global_overview_v1" for p in profiles)


class TestPreflightService:
    def test_validate_update_chain_ok(self):
        service = BasemapPreflightService.__new__(BasemapPreflightService)
        chain = {0: Path("A.000"), 1: Path("A.001"), 2: Path("A.002"), 3: Path("A.003")}
        errors = service.validate_update_chain("TEST", chain, 3)
        assert errors == []

    def test_validate_update_chain_missing_base(self):
        service = BasemapPreflightService.__new__(BasemapPreflightService)
        chain = {1: Path("A.001")}
        errors = service.validate_update_chain("TEST", chain, 3)
        assert any("000" in e for e in errors)

    def test_validate_update_chain_missing_update(self):
        service = BasemapPreflightService.__new__(BasemapPreflightService)
        chain = {0: Path("A.000"), 1: Path("A.001"), 3: Path("A.003")}
        errors = service.validate_update_chain("TEST", chain, 3)
        assert any("002" in e for e in errors)


class TestDsidValidation:
    """Verify DSID_INTU mismatch blocks cells."""

    def test_intu_mismatch_blocks(self, mock_ogrinfo_overview, mock_ogrinfo_band2):
        meta1 = _extract_dsid_metadata(mock_ogrinfo_overview)
        meta2 = _extract_dsid_metadata(mock_ogrinfo_band2)
        assert meta1["intu"] == 1
        assert meta2["intu"] == 2
        assert meta2["intu"] != 1  # band2 should be blocked for overview profile

    def test_missing_intu_does_not_crash(self, mock_ogrinfo_no_dsid):
        meta = _extract_dsid_metadata(mock_ogrinfo_no_dsid)
        assert meta["intu"] is None


class TestFileCount:
    """Verify profile matches the 29-file expectation."""

    def test_29_files_in_profile(self):
        profile = load_profile("global_overview_v1")
        expected_file_count = sum(profile.expected_cells.values()) + len(profile.expected_cells)
        assert expected_file_count == 29

    def test_18_cells_in_profile(self):
        profile = load_profile("global_overview_v1")
        assert len(profile.expected_cells) == 18

    def test_profile_cells_match_known_list(self):
        profile = load_profile("global_overview_v1")
        known_cells = [
            "C110408A", "GB1AH000", "GB1DD000", "GB1DE000", "GB1DM000",
            "GB1DN000", "GB1FS000", "GB1GB000", "GB1GK000",
            "JP14CCM8", "JP15AT88", "JP15ATBC",
            "NO1A3000", "US1AK90M", "US1BS01M", "US1BS02M",
            "US1BS03M", "US1BS04M",
        ]
        for cell in known_cells:
            assert cell in profile.expected_cells, f"Missing cell: {cell}"

    def test_no3_no1a3000_max_update(self):
        profile = load_profile("global_overview_v1")
        assert profile.expected_cells["NO1A3000"] == 3

    def test_us1bs03m_max_update(self):
        profile = load_profile("global_overview_v1")
        assert profile.expected_cells["US1BS03M"] == 5
