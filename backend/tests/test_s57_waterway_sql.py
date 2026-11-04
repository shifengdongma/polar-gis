from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.services.s57_waterway_catalog import classify_waterway
from app.services.s57_waterways import (
    WaterwayLayerRef,
    build_waterway_search_sql,
    decode_waterway_id,
    encode_waterway_id,
)


def layer(
    *,
    code="FAIRWY",
    fields=("objnam", "nobjnm", "inform", "status"),
    geometry=True,
    key="ogc_fid",
):
    return WaterwayLayerRef(
        layer_id=uuid4(),
        layer_code="s57_test_1_fairwy",
        layer_name="FAIRWY",
        dataset_id=uuid4(),
        dataset_code="s57_test",
        dataset_name="S-57 海图 TEST",
        version_no=1,
        source_cell="TEST",
        object_class=code,
        rule=classify_waterway(code),
        source_table="geo.ds_test_v1_fairwy",
        geometry_type="MultiLineString",
        fields=tuple(fields),
        key_column=key,
        key_type="int",
        geometry_column="geom" if geometry else None,
        feature_count=5,
        available=True,
        queryable=True,
        renderable=geometry,
        reason=None,
        updated_at=None,
    )


def payload(**overrides):
    return SimpleNamespace(
        keyword=overrides.get("keyword"),
        bbox=overrides.get("bbox"),
        page=overrides.get("page", 1),
        page_size=overrides.get("page_size", 20),
        object_classes=overrides.get("object_classes", ["FAIRWY"]),
        include_auxiliary=overrides.get("include_auxiliary", False),
    )


def test_union_uses_bound_keyword_and_bbox_not_interpolated_values():
    ref = layer()
    count_sql, rows_sql, params = build_waterway_search_sql(
        [ref, layer()],
        payload(keyword="' OR 1=1 --", bbox=(10.0, 70.0, 20.0, 80.0)),
    )
    assert "UNION ALL" in rows_sql
    assert "ST_MakeEnvelope" in rows_sql
    assert ":keyword_0" in rows_sql
    assert "' OR 1=1 --" not in rows_sql
    assert ":bbox_0_xmin" in rows_sql
    assert "ORDER BY layer_order, feature_key" in rows_sql
    assert "LIMIT :limit OFFSET :offset" in rows_sql
    assert params["keyword_0"] == "' OR 1=1 --"
    assert params["limit"] == 20
    assert count_sql.startswith("SELECT COUNT(*) FROM (")


def test_non_spatial_layer_is_skipped_for_bbox_search():
    ref = layer(fields=("objnam",), geometry=False)
    count_sql, rows_sql, params = build_waterway_search_sql(
        [ref], payload(bbox=(10.0, 70.0, 20.0, 80.0))
    )
    assert count_sql == ""
    assert rows_sql == ""
    assert params == {}


def test_keyword_layer_without_name_or_inform_fields_is_skipped():
    ref = layer(fields=("status",))
    count_sql, rows_sql, _ = build_waterway_search_sql([ref], payload(keyword="航道"))
    assert count_sql == ""
    assert rows_sql == ""


def test_antimeridian_bbox_splits_into_two_envelopes():
    ref = layer()
    _, rows_sql, params = build_waterway_search_sql(
        [ref], payload(bbox=(170.0, -10.0, -170.0, 10.0))
    )
    assert "bbox_0_axmin" in rows_sql
    assert "bbox_0_bxmin" in rows_sql
    assert " OR " in rows_sql
    assert params["bbox_0_axmin"] == -180.0
    assert params["bbox_0_bxmax"] == 180.0


def test_feature_id_roundtrip_and_rejects_tampering():
    layer_id = uuid4()
    encoded = encode_waterway_id(layer_id, "123")
    decoded_layer, decoded_key = decode_waterway_id(encoded)
    assert decoded_layer == layer_id
    assert decoded_key == "123"
    with pytest.raises(AppError):
        decode_waterway_id("not-base64")


def test_identifier_validation_rejects_injected_table():
    ref = layer()
    object.__setattr__(ref, "source_table", "geo.ds_fairwy; DROP TABLE layers")
    with pytest.raises(AppError):
        build_waterway_search_sql([ref], payload())


def test_property_rows_do_not_translate_raw_category_codes():
    from app.services.s57_waterways import _property_rows

    ref = layer(fields=("objnam", "nobjnm", "catfaw", "status", "drval1"))
    properties, raw = _property_rows(
        ref,
        {
            "objnam": "Fairway A",
            "nobjnm": "京杭运河",
            "catfaw": 1,
            "status": "1",
            "drval1": 12.5,
        },
    )
    by_field = {item["field"]: item for item in properties}
    assert by_field["OBJNAM"]["raw"] == "Fairway A"
    assert by_field["NOBJNM"]["raw"] == "京杭运河"
    # CAT* and STATUS keep the raw code; no invented enumeration translation.
    assert by_field["CATFAW"]["raw"] == 1
    assert by_field["CATFAW"]["labelZh"].startswith("S-57 类别属性")
    assert by_field["STATUS"]["raw"] == "1"
    assert "原始代码" in (by_field["STATUS"]["description"] or "")
    # Missing curated fields are explicitly marked as not provided.
    assert by_field["INFORM"]["provided"] is False
    assert by_field["INFORM"]["raw"] is None
    assert raw["catfaw"] == 1
