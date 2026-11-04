from app.services.s57_layer_catalog import (
    CORE_CHART,
    NAVIGATION_RECOMMENDED,
    OPTIONAL_THEMATIC,
    classify_s57_layer,
)
from app.services.s57_waterway_catalog import (
    S57_WATERWAY_ALL_CLASSES,
    S57_WATERWAY_AUXILIARY_CLASSES,
    S57_WATERWAY_OBJECT_CLASSES,
    WATERWAY_GROUP_ORDER,
    classify_waterway,
    normalize_object_class,
)


def test_primary_waterway_classes_match_task_candidate_set():
    assert S57_WATERWAY_OBJECT_CLASSES == frozenset(
        {
            "FAIRWY",
            "RECTRC",
            "NAVLNE",
            "TWRTPT",
            "TSSLPT",
            "TSSBND",
            "TSEZNE",
            "TSSRON",
            "CTNARE",
            "DRGARE",
            "CANALS",
        }
    )


def test_auxiliary_classes_are_separate_from_waterway_primary():
    assert S57_WATERWAY_AUXILIARY_CLASSES == frozenset(
        {"RESARE", "ACHARE", "BERTHS", "PILPNT", "DEPARE", "DEPCNT", "SOUNDG"}
    )
    assert S57_WATERWAY_OBJECT_CLASSES.isdisjoint(S57_WATERWAY_AUXILIARY_CLASSES)
    assert S57_WATERWAY_ALL_CLASSES == (
        S57_WATERWAY_OBJECT_CLASSES | S57_WATERWAY_AUXILIARY_CLASSES
    )


def test_groups_and_default_selection():
    assert WATERWAY_GROUP_ORDER == (
        "fairway_route",
        "traffic_separation",
        "restriction",
        "waterway_environment",
    )
    fairway = classify_waterway("FAIRWY")
    assert fairway is not None
    assert fairway.group == "fairway_route"
    assert fairway.name_zh == "航道"
    assert fairway.default_selected is True
    assert classify_waterway("CTNARE").default_selected is False
    assert classify_waterway("DRGARE").default_selected is False
    assert classify_waterway("DEPARE").auxiliary is True
    assert classify_waterway("DEPARE").name_zh == "水深区域"


def test_normalize_object_class_accepts_workspace_prefix_and_case():
    assert normalize_object_class("polar_gis:fairwy") == "FAIRWY"
    assert normalize_object_class(" FAIRWY ") == "FAIRWY"
    assert normalize_object_class("") == ""
    assert classify_waterway("polar_gis:fairwy").code == "FAIRWY"


def test_existing_s57_catalog_semantics_are_not_mutated():
    # The waterway taxonomy is additive: the legacy catalog keeps its exact
    # membership and FAIRWY/RECTRC/NAVLNE/TWRTPT remain optional_other.
    assert "FAIRWY" not in CORE_CHART
    assert "FAIRWY" not in NAVIGATION_RECOMMENDED
    assert "FAIRWY" not in OPTIONAL_THEMATIC
    assert classify_s57_layer("FAIRWY", "MultiLineString", True).load_profile == "optional_other"
    assert classify_s57_layer("CANALS", "MultiPolygon", False).load_profile == "optional_thematic"
