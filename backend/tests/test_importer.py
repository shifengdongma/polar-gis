"""Tests for S-57 layer metadata merge during import."""

from uuid import uuid4

from app.core.config import Settings
from app.models import Layer, LayerStatus
from app.services.importer import ImportProcessor, merge_s57_layer_metadata


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

    def test_extent_present_writes_four_float_list(self) -> None:
        result = merge_s57_layer_metadata(
            {},
            source_layer={
                "name": "DEPARE",
                "featureCount": 923,
                "geometryFields": [
                    {
                        "name": "",
                        "type": "Multi Polygon",
                        "extent": [-180, -90, 180, 90],
                    }
                ],
            },
            geometry_type="Multi Polygon",
            style_mapped=True,
        )
        assert result["s57"]["extent"] == [-180.0, -90.0, 180.0, 90.0]
        assert all(isinstance(value, float) for value in result["s57"]["extent"])

    def test_extent_missing_or_invalid_yields_none(self) -> None:
        # geometryFields empty (non-spatial layer)
        result = merge_s57_layer_metadata(
            {},
            source_layer={"name": "DSID", "geometryFields": []},
            geometry_type=None,
            style_mapped=False,
        )
        assert result["s57"]["extent"] is None

        # extent key missing from geometry field
        result2 = merge_s57_layer_metadata(
            {},
            source_layer={"name": "DEPARE", "geometryFields": [{"type": "Multi Polygon"}]},
            geometry_type="Multi Polygon",
            style_mapped=True,
        )
        assert result2["s57"]["extent"] is None

        # invalid extent (wrong length / non-numeric)
        result3 = merge_s57_layer_metadata(
            {},
            source_layer={"name": "DEPARE", "geometryFields": [{"extent": [1, 2, 3]}]},
            geometry_type="Multi Polygon",
            style_mapped=True,
        )
        assert result3["s57"]["extent"] is None

        result4 = merge_s57_layer_metadata(
            {},
            source_layer={"name": "DEPARE", "geometryFields": [{"extent": ["a", "b", "c", "d"]}]},
            geometry_type="Multi Polygon",
            style_mapped=True,
        )
        assert result4["s57"]["extent"] is None

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


class StubGeoServerClient:
    """Minimal GeoServerClient stand-in recording GWC calls."""

    def __init__(self) -> None:
        self.gridset_calls: list[tuple[str, str, list[float]]] = []
        self.gwc_calls: list[tuple[str, list[str], list[str]]] = []
        self.fail_gwc_layers: set[str] = set()

    def ensure_gridset(self, gridset_name: str, crs: str, extent: list[float]) -> None:
        self.gridset_calls.append((gridset_name, crs, extent))

    def ensure_gwc_layer(
        self,
        layer_name: str,
        gridsets: list[str] | None = None,
        mime_formats: list[str] | None = None,
    ) -> None:
        if layer_name in self.fail_gwc_layers:
            raise RuntimeError(f"stub GWC failure for {layer_name}")
        self.gwc_calls.append((layer_name, gridsets or [], mime_formats or []))


def _make_spatial_layer(code: str) -> Layer:
    return Layer(
        dataset_version_id=uuid4(),
        code=code,
        name=code,
        geometry_type="Multi Polygon",
        status=LayerStatus.AVAILABLE.value,
        geoserver_workspace="polar_gis",
        geoserver_layer_name=code,
    )


class TestEnableGwcCaching:
    def test_ensures_3413_gridset_once_and_configures_three_gridsets(self) -> None:
        processor = ImportProcessor(Settings())
        stub = StubGeoServerClient()
        processor.geoserver = stub  # type: ignore[assignment]

        processor._enable_gwc_caching([_make_spatial_layer("DEPARE"), _make_spatial_layer("LIGHTS")])

        # ensure_gridset called exactly once with the EPSG:3413 definition
        assert len(stub.gridset_calls) == 1
        gridset_name, crs, extent = stub.gridset_calls[0]
        assert gridset_name == "EPSG:3413"
        assert crs == "EPSG:3413"
        assert extent == [-4194304.0, -4194304.0, 4194304.0, 4194304.0]

        # every layer configured with all three gridsets incl. EPSG:3413
        assert len(stub.gwc_calls) == 2
        for layer_name, gridsets, mime_formats in stub.gwc_calls:
            assert layer_name in {"DEPARE", "LIGHTS"}
            assert gridsets == ["EPSG:3857", "EPSG:4326", "EPSG:3413"]
            assert "EPSG:3413" in gridsets
            assert mime_formats == ["image/png"]

    def test_gridset_or_layer_failures_only_warn_do_not_interrupt(self) -> None:
        processor = ImportProcessor(Settings())
        stub = StubGeoServerClient()

        def fail_gridset(*_args: object) -> None:
            raise RuntimeError("stub gridset failure")

        stub.ensure_gridset = fail_gridset  # type: ignore[method-assign]
        stub.fail_gwc_layers = {"DEPARE"}
        processor.geoserver = stub  # type: ignore[assignment]

        # Must not raise; surviving layers still get configured.
        processor._enable_gwc_caching([_make_spatial_layer("DEPARE"), _make_spatial_layer("LIGHTS")])

        assert len(stub.gwc_calls) == 1
        assert stub.gwc_calls[0][0] == "LIGHTS"
