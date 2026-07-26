from dataclasses import FrozenInstanceError
from itertools import combinations

import pytest

from app.services.s57_layer_catalog import (
    CORE_CHART,
    METADATA_QUALITY,
    NAVIGATION_RECOMMENDED,
    NON_SPATIAL,
    OPTIONAL_THEMATIC,
    classify_s57_layer,
    has_valid_geometry,
)

EXPECTED_CORE_CHART = {
    "COALNE",
    "LNDARE",
    "DEPARE",
    "DEPCNT",
    "SOUNDG",
    "SEAARE",
    "ICEARE",
    "OBSTRN",
    "WRECKS",
    "UWTROC",
    "CTNARE",
    "UNSARE",
}
EXPECTED_NAVIGATION_RECOMMENDED = {
    "LIGHTS",
    "FOGSIG",
    "BOYCAR",
    "BOYINB",
    "BOYISD",
    "BOYSAW",
    "BOYSPP",
    "BCNISD",
    "BCNSPP",
    "TOPMAR",
    "RTPBCN",
    "RDOSTA",
    "RDOCAL",
    "RETRFL",
    "RCRTCL",
    "RCTLPT",
    "TSSBND",
    "TSSLPT",
    "TSEZNE",
    "TSSRON",
    "RESARE",
    "DMPGRD",
    "HRBARE",
    "SLCONS",
}
EXPECTED_OPTIONAL_THEMATIC = {
    "ADMARE",
    "BUAARE",
    "BUISGL",
    "CANALS",
    "CBLSUB",
    "CONZNE",
    "COSARE",
    "CURENT",
    "EXEZNE",
    "FNCLNE",
    "FSHZNE",
    "LAKARE",
    "LNDELV",
    "LNDMRK",
    "LNDRGN",
    "LOCMAG",
    "MAGVAR",
    "MARCUL",
    "OFSPLF",
    "OSPARE",
    "PILPNT",
    "PIPSOL",
    "RIVERS",
    "SBDARE",
    "STSLNE",
    "TESARE",
}
EXPECTED_METADATA_QUALITY = {"M_COVR", "M_CSCL", "M_NPUB", "M_NSYS", "M_QUAL"}
EXPECTED_NON_SPATIAL = {"DSID", "C_AGGR"}

EXPECTED_PROFILES = {
    "core_chart": EXPECTED_CORE_CHART,
    "navigation_recommended": EXPECTED_NAVIGATION_RECOMMENDED,
    "optional_thematic": EXPECTED_OPTIONAL_THEMATIC,
    "metadata_quality": EXPECTED_METADATA_QUALITY,
    "non_spatial": EXPECTED_NON_SPATIAL,
}
PRODUCTION_PROFILES = {
    "core_chart": CORE_CHART,
    "navigation_recommended": NAVIGATION_RECOMMENDED,
    "optional_thematic": OPTIONAL_THEMATIC,
    "metadata_quality": METADATA_QUALITY,
    "non_spatial": NON_SPATIAL,
}


def test_production_catalog_sets_are_exact_and_disjoint() -> None:
    assert PRODUCTION_PROFILES == EXPECTED_PROFILES

    for left, right in combinations(PRODUCTION_PROFILES.values(), 2):
        assert left.isdisjoint(right)

    for profile, codes in EXPECTED_PROFILES.items():
        for code in codes:
            rule = classify_s57_layer(code, "Point", True)
            assert rule.load_profile == profile
            assert rule.object_name_zh.strip()


def test_normalizes_codes_and_assigns_display_priorities() -> None:
    assert classify_s57_layer("depare", "Multi Polygon", True).code == "DEPARE"
    assert classify_s57_layer("workspace: depare ", "Multi Polygon", True).code == "DEPARE"
    assert classify_s57_layer("DEPARE", "Multi Polygon", True).display_priority == 10
    assert classify_s57_layer("COALNE", "Line String", True).display_priority == 20
    assert classify_s57_layer("SOUNDG", "Point", True).display_priority == 30
    assert classify_s57_layer("WRECKS", "Point", True).display_priority == 40
    assert classify_s57_layer("LIGHTS", "Point", True).display_priority == 50
    assert classify_s57_layer("TSSBND", "Line String", True).display_priority == 60
    assert classify_s57_layer("RESARE", "Multi Polygon", True).display_priority == 70
    assert classify_s57_layer("ADMARE", "Multi Polygon", True).display_priority == 100
    assert classify_s57_layer("M_QUAL", "Multi Polygon", True).display_priority == 200
    assert classify_s57_layer("DSID", None, False).display_priority == 900


def test_assigns_stable_display_categories() -> None:
    expected = {
        "DEPARE": "bathymetry",
        "COALNE": "land_coast",
        "SOUNDG": "depth",
        "WRECKS": "hazard",
        "LIGHTS": "navigation_aid",
        "TSSBND": "routing",
        "RESARE": "restriction_harbor",
        "ADMARE": "optional_thematic",
        "M_QUAL": "metadata_quality",
        "DSID": "non_spatial",
    }
    for code, category in expected.items():
        assert classify_s57_layer(code, "Point", True).display_category == category


def test_recommendation_requires_known_auto_profile_and_style_mapping() -> None:
    for code in CORE_CHART | NAVIGATION_RECOMMENDED:
        mapped = classify_s57_layer(code, "Point", True)
        unmapped = classify_s57_layer(code, "Point", False)
        assert mapped.recommended is True
        assert unmapped.recommended is False
        assert unmapped.load_profile in {"core_chart", "navigation_recommended"}
        assert mapped.default_visible is False
        assert unmapped.default_visible is False

    metadata = classify_s57_layer("M_QUAL", "Multi Polygon", True)
    optional = classify_s57_layer("ADMARE", "Multi Polygon", True)
    assert metadata.recommended is False
    assert optional.recommended is False


def test_non_spatial_codes_never_render_even_with_geometry() -> None:
    for code in NON_SPATIAL:
        assert classify_s57_layer(code, "Point", True).renderable is False


def test_unknown_layers_fall_back_by_geometry_and_prefix() -> None:
    spatial = classify_s57_layer("newobj", "GeometryCollection", False)
    assert spatial.code == "NEWOBJ"
    assert spatial.load_profile == "optional_other"
    assert spatial.display_category == "optional_other"
    assert spatial.display_priority == 100
    assert spatial.renderable is True
    assert spatial.recommended is False

    metadata = classify_s57_layer("M_NEW", "Polygon", True)
    assert metadata.load_profile == "metadata_quality"
    assert metadata.display_category == "metadata_quality"
    assert metadata.display_priority == 200
    assert metadata.renderable is True
    assert metadata.recommended is False

    for code in ("NEWOBJ", "C_NEW"):
        non_spatial = classify_s57_layer(code, None, True)
        assert non_spatial.load_profile == "non_spatial"
        assert non_spatial.display_category == "non_spatial"
        assert non_spatial.display_priority == 900
        assert non_spatial.renderable is False
        assert non_spatial.recommended is False


def test_geometry_validation_rejects_only_explicit_non_geometry_values() -> None:
    for geometry_type in (None, "", "  ", "unknown", "NONE", "无", "无几何", "null"):
        assert has_valid_geometry(geometry_type) is False

    for geometry_type in (
        "Point",
        "Line String",
        "Multi Polygon",
        "GeometryCollection",
        "Curve",
    ):
        assert has_valid_geometry(geometry_type) is True


def test_rules_have_stable_sort_key_and_are_immutable() -> None:
    rules = [
        classify_s57_layer("WRECKS", "Point", True),
        classify_s57_layer("COALNE", "Line String", True),
        classify_s57_layer("OBSTRN", "Point", True),
        classify_s57_layer("DEPARE", "Multi Polygon", True),
    ]

    assert [rule.code for rule in sorted(rules, key=lambda rule: rule.sort_key)] == [
        "DEPARE",
        "COALNE",
        "OBSTRN",
        "WRECKS",
    ]
    assert rules[0].sort_key == (40, "WRECKS")

    with pytest.raises(FrozenInstanceError):
        rules[0].code = "CHANGED"  # type: ignore[misc]
