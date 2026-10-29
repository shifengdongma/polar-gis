"""Risk model tests: legacy reproducibility and real_v1 missing semantics."""

import pytest

from app.navigation.risk.evaluator import RiskInput, evaluate_risk, risk_component_quality
from app.navigation.vessel.models import VesselProfile


def vessel() -> VesselProfile:
    return VesselProfile(
        id="xuelong2",
        name="雪龙2号",
        vessel_type="极地科学考察破冰船",
        length_m=122.5,
        beam_m=22.32,
        design_draft_m=7.85,
        total_propulsion_power_mw=15.0,
        service_speed_min_kn=12,
        service_speed_max_kn=15,
        maximum_speed_kn=18,
        continuous_ice_thickness_m=1.5,
        safety_draft_m=7.85,
        safety_power_mw=15.0,
        safety_speed_limit_kn=18,
        ukc_m=2.0,
    )


def payload(**overrides) -> RiskInput:
    base = dict(
        latitude=70.0,
        longitude=120.0,
        day_of_year=46,
        depth_m=100.0,
        ice_concentration=0.5,
        ice_thickness_m=0.5,
        wind_speed_ms=10.0,
        wind_direction_from_deg=270.0,
        wave_height_m=2.0,
        wave_direction_from_deg=240.0,
        current_u_ms=0.2,
        current_v_ms=-0.1,
        quality={
            "ice": "real",
            "depth": "real",
            "wind": "real",
            "wave": "real",
            "fog": "missing",
        },
        sources={"ice": "test"},
    )
    base.update(overrides)
    return RiskInput(**base)


def test_legacy_ice_formula_golden() -> None:
    result = evaluate_risk(payload(), vessel(), "legacy_v1")
    # load = 0.5*(0.35+0.65*(0.5/1.5)) = 0.283333...; risk=(load-0.12)/1.15
    assert result.ice_risk == pytest.approx((0.5 * (0.35 + 0.65 * (0.5 / 1.5)) - 0.12) / 1.15)
    assert result.traversable is True
    assert result.combined_risk is not None
    assert result.model_version == "legacy_v1"


def test_legacy_missing_depth_becomes_blocking_not_zero() -> None:
    result = evaluate_risk(payload(depth_m=None), vessel(), "legacy_v1")
    assert result.depth_risk == 1.0
    assert result.traversable is False
    assert result.blocked_reason == "shallow_water"


def test_real_missing_depth_is_unknown_not_safe() -> None:
    result = evaluate_risk(payload(depth_m=None), vessel(), "real_v1")
    assert result.depth_risk is None
    assert result.combined_risk is None
    assert result.traversable is None
    assert result.combined_quality == "unknown"


def test_real_missing_ice_thickness_is_unknown() -> None:
    result = evaluate_risk(payload(ice_thickness_m=None), vessel(), "real_v1")
    assert result.ice_risk is None
    assert result.combined_risk is None
    assert result.traversable is None


def test_real_missing_wind_is_excluded_and_prior_marked_missing() -> None:
    result = evaluate_risk(payload(wind_speed_ms=None), vessel(), "real_v1")
    assert result.wind_risk is None
    assert result.combined_risk is not None
    assert result.quality["wind_prior"] == "missing"
    assert risk_component_quality(result)["wind"] == "missing"


def test_real_fog_is_null_and_does_not_become_zero() -> None:
    result = evaluate_risk(payload(), vessel(), "real_v1")
    assert result.fog_risk is None
    assert result.combined_risk is not None
    assert risk_component_quality(result)["fog"] == "missing"


def test_land_zero_depth_blocks() -> None:
    result = evaluate_risk(payload(depth_m=0.0), vessel(), "real_v1")
    assert result.depth_risk == 1.0
    assert result.traversable is False
    assert result.blocked_reason == "land"


def test_ice_load_blocks_at_reference_threshold() -> None:
    result = evaluate_risk(
        payload(ice_concentration=1.0, ice_thickness_m=2.2), vessel(), "legacy_v1"
    )
    # multi-year factor 1.35; load = 1.0 * (0.35 + 0.65*1.5) * 1.35 = 1.35
    assert result.ice_risk == pytest.approx(1.0)
    assert result.traversable is False
    assert result.blocked_reason == "ice_load"


def test_real_combined_renormalises_available_weights() -> None:
    result = evaluate_risk(payload(wind_speed_ms=None), vessel(), "real_v1")
    available = {
        "ice": result.ice_risk,
        "depth": result.depth_risk,
        "wind": None,
        "wave": result.wave_risk,
        "fog": None,
    }
    weights = {"ice": 0.4, "depth": 0.2, "wind": 0.1, "wave": 0.1}
    total = sum(weights[key] for key, value in available.items() if value is not None)
    expected = sum(weights[key] * value for key, value in available.items() if value is not None) / total
    assert result.combined_risk == pytest.approx(expected)
