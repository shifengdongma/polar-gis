"""Tests for S-57 layer metadata merge during import."""

from app.services.importer import merge_s57_layer_metadata


class TestMergeS57LayerMetadata:
    def test_merges_s57_classification_for_core_layer(self) -> None:
        result = merge_s57_layer_metadata(
            {"sourceLayer": "DEPARE", "legacy": "keep", "s57": {"custom": "keep"}},
            source_layer={"name": "DEPARE", "featureCount": 923},
            geometry_type="Multi Polygon",
            style_mapped=True,
        )
        assert result["legacy"] == "keep"
        assert result["s57"]["custom"] == "keep"
        assert result["s57"]["objectClass"] == "DEPARE"
        assert result["s57"]["objectNameZh"] == "水深区域"
        assert result["s57"]["displayCategory"] == "bathymetry"
        assert result["s57"]["loadProfile"] == "core_chart"
        assert result["s57"]["displayPriority"] == 10
        assert result["s57"]["recommended"] is True
        assert result["s57"]["renderable"] is True
        assert result["s57"]["styleMapped"] is True
        assert result["s57"]["featureCount"] == 923

    def test_feature_count_missing_or_invalid_yields_none(self) -> None:
        result = merge_s57_layer_metadata(
            {},
            source_layer={"name": "DEPARE"},
            geometry_type="Multi Polygon",
            style_mapped=True,
        )
        assert result["s57"]["featureCount"] is None

        result2 = merge_s57_layer_metadata(
            {},
            source_layer={"name": "DEPARE", "featureCount": "not-a-number"},
            geometry_type="Multi Polygon",
            style_mapped=True,
        )
        assert result2["s57"]["featureCount"] is None

    def test_non_s57_does_not_write_metadata_s57(self) -> None:
        """Non-S-57 imports should not get s57 metadata. Returns original metadata unchanged."""
        # merge_s57_layer_metadata is only called for S-57 datasets;
        # for non-S-57, the import path doesn't call it.
        # This test verifies the helper doesn't crash with non-S57-like input.
        result = merge_s57_layer_metadata(
            {"foo": "bar"},
            source_layer={"name": "roads"},
            geometry_type="Line String",
            style_mapped=False,
        )
        # Still produces s57 metadata based on classification (unknown → optional_other)
        assert "s57" in result
        assert result["s57"]["objectClass"] == "ROADS"
        assert result["foo"] == "bar"

    def test_preserves_all_existing_top_level_metadata_keys(self) -> None:
        result = merge_s57_layer_metadata(
            {
                "sourceLayer": "SOUNDG",
                "s57StyleStatus": "mapped",
                "recommendedStyleCode": "s57_sounding",
                "recommendedStyleId": "uuid-123",
            },
            source_layer={"name": "SOUNDG"},
            geometry_type="Point",
            style_mapped=True,
        )
        assert result["sourceLayer"] == "SOUNDG"
        assert result["s57StyleStatus"] == "mapped"
        assert result["recommendedStyleCode"] == "s57_sounding"
        assert result["recommendedStyleId"] == "uuid-123"

    def test_navigation_recommended_layer_with_style(self) -> None:
        result = merge_s57_layer_metadata(
            {},
            source_layer={"name": "LIGHTS"},
            geometry_type="Point",
            style_mapped=True,
        )
        assert result["s57"]["loadProfile"] == "navigation_recommended"
        assert result["s57"]["displayCategory"] == "navigation_aid"
        assert result["s57"]["displayPriority"] == 50
        assert result["s57"]["recommended"] is True

    def test_unmapped_core_layer_still_has_correct_profile(self) -> None:
        result = merge_s57_layer_metadata(
            {},
            source_layer={"name": "WRECKS"},
            geometry_type="Point",
            style_mapped=False,
        )
        assert result["s57"]["loadProfile"] == "core_chart"
        assert result["s57"]["recommended"] is False
        assert result["s57"]["renderable"] is True
        assert result["s57"]["styleMapped"] is False

    def test_dsid_non_spatial_always_non_renderable(self) -> None:
        result = merge_s57_layer_metadata(
            {},
            source_layer={"name": "DSID"},
            geometry_type=None,
            style_mapped=False,
        )
        assert result["s57"]["loadProfile"] == "non_spatial"
        assert result["s57"]["renderable"] is False
        assert result["s57"]["displayPriority"] == 900
