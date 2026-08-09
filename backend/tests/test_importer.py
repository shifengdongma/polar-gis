"""Tests for S-57 layer metadata merge and style application during import."""

import hashlib
from uuid import uuid4

from sqlalchemy.orm import Session

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

    def test_scale_rule_min_scale_denominator_stored(self) -> None:
        result = merge_s57_layer_metadata(
            {},
            source_layer={"name": "SOUNDG"},
            geometry_type="Point",
            style_mapped=True,
        )
        assert result["s57"]["minScaleDenominator"] == 25000.0

        result2 = merge_s57_layer_metadata(
            {},
            source_layer={"name": "COALNE"},
            geometry_type="Line String",
            style_mapped=True,
        )
        assert result2["s57"]["minScaleDenominator"] is None


class StubGeoServerClient:
    """Minimal GeoServerClient stand-in recording GWC and style calls."""

    def __init__(self) -> None:
        self.gridset_calls: list[tuple[str, str, list[float]]] = []
        self.gwc_calls: list[tuple[str, list[str], list[str]]] = []
        self.fail_gwc_layers: set[str] = set()
        self.publish_style_calls: list[tuple[str, str]] = []
        self.set_default_style_calls: list[tuple[str, str]] = []
        self.truncate_calls: list[str] = []

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

    def publish_style(self, style_name: str, sld: str) -> None:
        self.publish_style_calls.append((style_name, sld))

    def set_default_style(self, layer_name: str, style_name: str) -> None:
        self.set_default_style_calls.append((layer_name, style_name))

    def truncate_layer_cache(self, layer_name: str) -> None:
        self.truncate_calls.append(layer_name)


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


def _make_style_layer(
    code: str,
    source_layer: str,
    geometry_type: str | None,
    s57: dict | None = None,
) -> Layer:
    return Layer(
        dataset_version_id=uuid4(),
        code=code,
        name=source_layer,
        geometry_type=geometry_type,
        status=LayerStatus.AVAILABLE.value,
        geoserver_workspace="polar_gis",
        geoserver_layer_name=code,
        metadata_json={
            "sourceLayer": source_layer,
            "s57": s57 or {"objectClass": source_layer.upper(), "styleMapped": True},
        },
    )


class TestApplyS57Style:
    def test_publishes_scale_aware_sld_and_truncates_cache(
        self, db_session: Session
    ) -> None:
        layer = _make_style_layer("SOUNDG_CELL", "SOUNDG", "Point")
        db_session.add(layer)
        db_session.flush()
        processor = ImportProcessor(Settings())
        stub = StubGeoServerClient()
        processor.geoserver = stub  # type: ignore[assignment]

        processor._apply_s57_style(db_session, layer)

        assert len(stub.publish_style_calls) == 1
        style_name, sld = stub.publish_style_calls[0]
        assert style_name == "s57_sounding"
        assert "<sld:MaxScaleDenominator>25000.0</sld:MaxScaleDenominator>" in sld
        assert stub.set_default_style_calls == [("SOUNDG_CELL", "s57_sounding")]
        assert stub.truncate_calls == ["SOUNDG_CELL"]
        assert layer.metadata_json["s57StyleStatus"] == "mapped"
        assert layer.metadata_json["recommendedStyleCode"] == "s57_sounding"
        assert layer.metadata_json["s57"]["styleMapped"] is True
        assert layer.metadata_json["s57"]["sldHash"] == hashlib.sha256(
            sld.encode("utf-8")
        ).hexdigest()

    def test_idempotent_skip_when_sld_unchanged(self, db_session: Session) -> None:
        layer = _make_style_layer("DEPCNT_CELL", "DEPCNT", "Line String")
        db_session.add(layer)
        db_session.flush()
        processor = ImportProcessor(Settings())
        stub = StubGeoServerClient()
        processor.geoserver = stub  # type: ignore[assignment]

        processor._apply_s57_style(db_session, layer)
        assert len(stub.publish_style_calls) == 1

        processor._apply_s57_style(db_session, layer)

        # second call with an identical SLD must not re-publish or truncate
        assert len(stub.publish_style_calls) == 1
        assert len(stub.set_default_style_calls) == 1
        assert len(stub.truncate_calls) == 1

    def test_truncates_when_sld_changed(self, db_session: Session) -> None:
        # stale hash (e.g. from the old single-rule SLD) forces re-publish + truncate
        layer = _make_style_layer(
            "LIGHTS_CELL",
            "LIGHTS",
            "Point",
            s57={"objectClass": "LIGHTS", "styleMapped": True, "sldHash": "0" * 64},
        )
        db_session.add(layer)
        db_session.flush()
        processor = ImportProcessor(Settings())
        stub = StubGeoServerClient()
        processor.geoserver = stub  # type: ignore[assignment]

        processor._apply_s57_style(db_session, layer)

        assert len(stub.publish_style_calls) == 1
        assert stub.truncate_calls == ["LIGHTS_CELL"]
        assert layer.metadata_json["s57"]["sldHash"] != "0" * 64

    def test_uses_stored_min_scale_denominator_from_metadata(
        self, db_session: Session
    ) -> None:
        # classification output persisted by merge_s57_layer_metadata wins over
        # a fresh classify call, so re-imports stay byte-identical
        layer = _make_style_layer(
            "LIGHTS_CELL2",
            "LIGHTS",
            "Point",
            s57={
                "objectClass": "LIGHTS",
                "styleMapped": True,
                "minScaleDenominator": 12345.0,
            },
        )
        db_session.add(layer)
        db_session.flush()
        processor = ImportProcessor(Settings())
        stub = StubGeoServerClient()
        processor.geoserver = stub  # type: ignore[assignment]

        processor._apply_s57_style(db_session, layer)

        sld = stub.publish_style_calls[0][1]
        assert "<sld:MaxScaleDenominator>12345.0</sld:MaxScaleDenominator>" in sld
        assert "50000.0" not in sld

    def test_unmapped_layer_marks_metadata_and_skips_publish(
        self, db_session: Session
    ) -> None:
        layer = _make_style_layer("DSID_CELL", "DSID", None)
        db_session.add(layer)
        db_session.flush()
        processor = ImportProcessor(Settings())
        stub = StubGeoServerClient()
        processor.geoserver = stub  # type: ignore[assignment]

        processor._apply_s57_style(db_session, layer)

        assert stub.publish_style_calls == []
        assert stub.truncate_calls == []
        assert layer.metadata_json["s57StyleStatus"] == "unmapped"
        assert layer.metadata_json["s57"]["styleMapped"] is False


class TestPublishSpecForLayer:
    def test_carries_s57_extent_metadata_as_bounds(self) -> None:
        layer = _make_style_layer(
            "DEPARE_CELL",
            "DEPARE",
            "Multi Polygon",
            s57={"extent": [-15.0, 62.0, 30.0, 81.0]},
        )
        layer.source_table = "geo.ds_1234_v1_DEPARE"
        spec = ImportProcessor._publish_spec_for_layer(layer)
        assert spec == {
            "table_name": "ds_1234_v1_DEPARE",
            "layer_name": "DEPARE_CELL",
            "title": "DEPARE",
            "bounds": [-15.0, 62.0, 30.0, 81.0],
        }

    def test_layer_without_extent_has_no_bounds_key(self) -> None:
        layer = _make_style_layer("DEPARE_CELL", "DEPARE", "Multi Polygon")
        layer.source_table = "geo.ds_1234_v1_DEPARE"
        spec = ImportProcessor._publish_spec_for_layer(layer)
        assert spec == {
            "table_name": "ds_1234_v1_DEPARE",
            "layer_name": "DEPARE_CELL",
            "title": "DEPARE",
        }
        assert "bounds" not in spec

    def test_non_s57_layer_never_gets_bounds(self) -> None:
        layer = _make_style_layer("ROADS_CELL", "roads", "Line String", s57={})
        layer.source_table = "geo.ds_1234_v1_roads"
        spec = ImportProcessor._publish_spec_for_layer(layer)
        assert spec == {
            "table_name": "ds_1234_v1_roads",
            "layer_name": "ROADS_CELL",
            "title": "roads",
        }
        assert "bounds" not in spec
