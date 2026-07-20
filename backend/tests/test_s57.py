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
