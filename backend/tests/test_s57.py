from pathlib import Path

import pytest

from app.core.errors import AppError
from app.services.s57 import identify_s57_file, validate_s57_update
from app.services.s57_styles import preset_for_object_class


def test_identify_s57_base_cell() -> None:
    identity = identify_s57_file(Path("RU4AB123.000"))
    assert identity.cell_name == "RU4AB123"
    assert identity.update_number == 0


def test_validate_continuous_update() -> None:
    identity = identify_s57_file(Path("RU4AB123.002"))
    validate_s57_update(identity, "RU4AB123", 1)


def test_reject_update_gap() -> None:
    identity = identify_s57_file(Path("RU4AB123.002"))
    with pytest.raises(AppError) as error:
        validate_s57_update(identity, "RU4AB123", 0)
    assert error.value.code == "S57_UPDATE_GAP"


def test_reject_other_cell() -> None:
    identity = identify_s57_file(Path("RU4ZZ999.001"))
    with pytest.raises(AppError) as error:
        validate_s57_update(identity, "RU4AB123", 0)
    assert error.value.code == "S57_CELL_MISMATCH"


def test_core_s57_object_classes_have_valid_sld_presets() -> None:
    for object_class in ["COALNE", "DEPCNT", "SOUNDG", "LIGHTS", "WRECKS", "RESARE"]:
        preset = preset_for_object_class(object_class)
        assert preset is not None
        sld = preset.render_sld()
        assert "StyledLayerDescriptor" in sld
        assert preset.code in sld

    assert preset_for_object_class("UNMAPPED") is None


def test_render_sld_with_max_scale_denominator() -> None:
    # Direction lock: production renders "show SOUNDG when SD ≤ 25000" via
    # max_scale_denominator (a MinScaleDenominator would invert the rule).
    preset = preset_for_object_class("SOUNDG")
    assert preset is not None
    sld = preset.render_sld(max_scale_denominator=25000.0)
    assert "<sld:MaxScaleDenominator>25000.0</sld:MaxScaleDenominator>" in sld
    assert "MinScaleDenominator" not in sld
    # scale element must sit inside the Rule, before the symbolizer
    assert sld.index("MaxScaleDenominator") < sld.index("PointSymbolizer")


def test_render_sld_with_min_and_max_scale_denominators() -> None:
    preset = preset_for_object_class("SOUNDG")
    assert preset is not None
    sld = preset.render_sld(
        min_scale_denominator=25000.0,
        max_scale_denominator=100000.0,
    )
    assert "<sld:MinScaleDenominator>25000.0</sld:MinScaleDenominator>" in sld
    assert "<sld:MaxScaleDenominator>100000.0</sld:MaxScaleDenominator>" in sld
    assert sld.index("MinScaleDenominator") < sld.index("MaxScaleDenominator")
    assert sld.index("MaxScaleDenominator") < sld.index("PointSymbolizer")


def test_render_sld_without_scale_omits_denominators() -> None:
    """Backward compatibility: no-arg render_sld stays free of scale elements."""
    preset = preset_for_object_class("COALNE")
    assert preset is not None
    sld = preset.render_sld()
    assert "MinScaleDenominator" not in sld
    assert "MaxScaleDenominator" not in sld
