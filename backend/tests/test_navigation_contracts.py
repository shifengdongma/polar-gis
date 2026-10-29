"""Contract tests for the navigation foundation layer."""

from datetime import UTC, datetime, timedelta
from math import isclose, pi

import pytest
from pydantic import ValidationError

from app.navigation.contracts import (
    DataQuality,
    FeasibilityStatus,
    TimeMatchInfo,
    TimeMetadata,
    WGS84Position,
    available_at_decision_time,
    combine_quality,
    from_bearing_speed_to_en,
    from_bearing_to_to_bearing,
    knots_to_metres_per_second,
    metres_per_second_to_knots,
    metres_to_nautical_miles,
    nautical_miles_to_metres,
    to_bearing_speed_to_en,
    within_max_lag,
    wrap_2pi,
)


def test_nautical_and_knot_conversions_are_exact():
    assert nautical_miles_to_metres(1.0) == 1852.0
    assert metres_to_nautical_miles(1852.0) == 1.0
    assert isclose(knots_to_metres_per_second(1.0), 1852.0 / 3600.0, rel_tol=0, abs_tol=1e-15)
    assert isclose(metres_per_second_to_knots(1852.0 / 3600.0), 1.0, rel_tol=0, abs_tol=1e-12)


def test_bearing_wraps_and_from_to_reversal():
    assert isclose(wrap_2pi(2 * pi + 0.25), 0.25)
    assert isclose(wrap_2pi(-0.25), 2 * pi - 0.25)
    assert isclose(from_bearing_to_to_bearing(0.0), pi)
    assert isclose(from_bearing_to_to_bearing(pi / 2), 3 * pi / 2)


def test_wind_from_270_points_east():
    # Meteorological FROM 270° (west) means the air moves toward east.
    east, north = from_bearing_speed_to_en(10.0, 3 * pi / 2)
    assert isclose(east, 10.0, abs_tol=1e-12)
    assert isclose(north, 0.0, abs_tol=1e-12)


def test_current_to_090_points_east():
    east, north = to_bearing_speed_to_en(0.5, pi / 2)
    assert isclose(east, 0.5, abs_tol=1e-12)
    assert isclose(north, 0.0, abs_tol=1e-12)


def test_time_match_rejects_naive_and_normalizes_utc():
    naive = datetime(2025, 2, 15, 12, 0, 0)
    with pytest.raises(ValidationError):
        TimeMatchInfo(requested_time=naive)

    match = TimeMatchInfo(
        requested_time=datetime(2025, 2, 15, 12, 0, tzinfo=UTC),
        matched_time=datetime(2025, 2, 15, 13, 0, tzinfo=UTC),
        delta_seconds=3600.0,
        quality="within_tolerance",
    )
    assert match.matched_time is not None
    assert match.matched_time.utcoffset() == timedelta(0)


def test_time_metadata_availability_is_three_valued():
    decision = datetime(2025, 2, 15, 12, 0, tzinfo=UTC)
    assert available_at_decision_time(TimeMetadata(), decision) is None
    assert (
        available_at_decision_time(
            TimeMetadata(issue_time=decision - timedelta(hours=1)), decision
        )
        is True
    )
    assert (
        available_at_decision_time(
            TimeMetadata(issue_time=decision + timedelta(hours=1)), decision
        )
        is False
    )


def test_max_lag_is_three_valued():
    assert within_max_lag(3600.0, 6.0) is True
    assert within_max_lag(7 * 3600.0, 6.0) is False
    assert within_max_lag(None, 6.0) is None
    assert within_max_lag(3600.0, None) is None


def test_data_quality_combination_is_conservative():
    assert combine_quality([DataQuality.REAL, DataQuality.REAL]) is DataQuality.REAL
    assert combine_quality([DataQuality.REAL, DataQuality.SYNTHETIC]) is DataQuality.SYNTHETIC
    assert combine_quality([DataQuality.REAL, DataQuality.MISSING]) is DataQuality.UNKNOWN
    assert combine_quality([]) is DataQuality.UNKNOWN


def test_feasibility_status_cannot_be_used_as_bool():
    with pytest.raises(TypeError):
        bool(FeasibilityStatus.PASS)


def test_wgs84_position_bounds():
    WGS84Position(latitude_deg=78.0, longitude_deg=125.0)
    with pytest.raises(ValidationError):
        WGS84Position(latitude_deg=91.0, longitude_deg=125.0)
    with pytest.raises(ValidationError):
        WGS84Position(latitude_deg=78.0, longitude_deg=181.0)
