"""Tests for map_render_plan — combined-layer render bundle service."""

from dataclasses import FrozenInstanceError

import pytest

from app.services.map_render_plan import (
    MAX_LAYERS_PER_BUNDLE,
    BundleConfig,
    LayerRenderInput,
    build_bundles,
    bundle_cache_key,
    compute_bundle_id,
    get_bucket_for_layer,
)

# ── Helpers ────────────────────────────────────────────────────────────────

def _layer(
    *,
    layer_id: str = "l-001",
    geoserver_layer_name: str = "pg:l_001",
    style_name: str = "pg:s_default",
    object_class: str = "DEPARE",
    display_category: str = "bathymetry",
    display_priority: int = 10,
    opacity: float = 1.0,
    extent: tuple[float, ...] | None = (-10.0, 60.0, 10.0, 75.0),
    min_zoom: int | None = None,
    max_zoom: int | None = None,
    render_standalone: bool = False,
) -> LayerRenderInput:
    return LayerRenderInput(
        layer_id=layer_id,
        geoserver_layer_name=geoserver_layer_name,
        style_name=style_name,
        object_class=object_class,
        display_category=display_category,
        display_priority=display_priority,
        opacity=opacity,
        extent=extent,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        render_standalone=render_standalone,
    )


# ── get_bucket_for_layer ───────────────────────────────────────────────────

class TestGetBucketForLayer:
    def test_bathymetry_maps_to_area_fill(self):
        bucket = get_bucket_for_layer("bathymetry", "DEPARE")
        assert bucket is not None
        assert bucket.bucket_id == "area_fill"

    def test_depth_depcnt_overrides_to_line_structure(self):
        bucket = get_bucket_for_layer("depth", "DEPCNT")
        assert bucket is not None
        assert bucket.bucket_id == "line_structure"

    def test_optional_thematic_soundg_overrides_to_hazard_detail(self):
        bucket = get_bucket_for_layer("optional_thematic", "SOUNDG")
        assert bucket is not None
        assert bucket.bucket_id == "hazard_detail"

    def test_hazard_maps_to_hazard_detail(self):
        bucket = get_bucket_for_layer("hazard", "WRECKS")
        assert bucket is not None
        assert bucket.bucket_id == "hazard_detail"

    def test_navigation_aid_maps_correctly(self):
        bucket = get_bucket_for_layer("navigation_aid", "LIGHTS")
        assert bucket is not None
        assert bucket.bucket_id == "navigation_aid"

    def test_routing_maps_to_line_structure(self):
        bucket = get_bucket_for_layer("routing", "TSSBND")
        assert bucket is not None
        assert bucket.bucket_id == "line_structure"

    def test_non_spatial_returns_none(self):
        bucket = get_bucket_for_layer("non_spatial", "DSID")
        assert bucket is None

    def test_land_coast_coalne_overrides_to_line(self):
        bucket = get_bucket_for_layer("land_coast", "COALNE")
        assert bucket is not None
        assert bucket.bucket_id == "line_structure"

    def test_land_coast_lndare_overrides_to_area(self):
        bucket = get_bucket_for_layer("land_coast", "LNDARE")
        assert bucket is not None
        assert bucket.bucket_id == "area_fill"

    def test_restriction_harbor_slcons_overrides_to_line(self):
        bucket = get_bucket_for_layer("restriction_harbor", "SLCONS")
        assert bucket is not None
        assert bucket.bucket_id == "line_structure"

    def test_unknown_category_falls_back_to_optional_other(self):
        bucket = get_bucket_for_layer("some_unknown_category", "XXXXX")
        assert bucket is not None
        assert bucket.bucket_id == "optional_other"


# ── build_bundles ──────────────────────────────────────────────────────────

class TestBuildBundles:
    def test_single_bucket_produces_one_bundle(self):
        layers = [
            _layer(layer_id="l-1", object_class="DEPARE", display_category="bathymetry"),
            _layer(layer_id="l-2", object_class="SEAARE", display_category="bathymetry"),
        ]
        bundles, standalones = build_bundles(layers, "core_chart", "EPSG:3857")
        assert len(bundles) == 1
        assert len(standalones) == 0
        assert bundles[0].bucket == "area_fill"
        assert bundles[0].layer_ids == ["l-1", "l-2"]

    def test_layers_and_styles_strictly_aligned(self):
        layers = [
            _layer(layer_id="l-1", geoserver_layer_name="pg:a", style_name="pg:sa", object_class="DEPARE"),
            _layer(layer_id="l-2", geoserver_layer_name="pg:b", style_name="pg:sb", object_class="SEAARE"),
        ]
        bundles, _ = build_bundles(layers, "core_chart", "EPSG:3857")
        assert bundles[0].layer_names == ["pg:a", "pg:b"]
        assert bundles[0].styles == ["pg:sa", "pg:sb"]
        # Same index → same layer
        for i in range(2):
            assert bundles[0].layer_names[i] == f"pg:{chr(97 + i)}"
            assert bundles[0].styles[i] == f"pg:s{chr(97 + i)}"

    def test_different_zindex_categories_not_merged(self):
        layers = [
            _layer(layer_id="l-1", object_class="DEPARE", display_category="bathymetry", display_priority=10),
            _layer(layer_id="l-2", object_class="LIGHTS", display_category="navigation_aid", display_priority=50),
        ]
        bundles, _ = build_bundles(layers, "navigation_recommended", "EPSG:3857")
        # Two different buckets → two bundles
        assert len(bundles) == 2
        bucket_ids = {b.bucket for b in bundles}
        assert bucket_ids == {"area_fill", "navigation_aid"}

    def test_different_opacities_not_merged_in_bundle(self):
        """Layers with non-default opacity become standalone, not bundled."""
        layers = [
            _layer(layer_id="l-1", object_class="DEPARE", opacity=1.0),
            _layer(layer_id="l-2", object_class="SEAARE", opacity=0.5),  # custom opacity
        ]
        bundles, standalones = build_bundles(layers, "core_chart", "EPSG:3857")
        # l-1 → bundle, l-2 → standalone
        assert len(bundles) == 1
        assert len(standalones) == 1
        assert standalones[0].layer_id == "l-2"
        assert standalones[0].opacity == 0.5
        assert standalones[0].reason == "custom_opacity"

    def test_non_spatial_layers_excluded(self):
        layers = [
            _layer(layer_id="l-1", object_class="DEPARE", display_category="bathymetry"),
            _layer(layer_id="l-2", object_class="DSID", display_category="non_spatial"),
        ]
        bundles, standalones = build_bundles(layers, "core_chart", "EPSG:3857")
        # non_spatial excluded entirely
        assert len(bundles) == 1
        assert bundles[0].layer_ids == ["l-1"]
        assert len(standalones) == 0

    def test_render_standalone_layers_are_standalone(self):
        layers = [
            _layer(layer_id="l-1", object_class="DEPARE"),
            _layer(layer_id="l-2", object_class="SEAARE", render_standalone=True),
        ]
        bundles, standalones = build_bundles(layers, "core_chart", "EPSG:3857")
        assert len(bundles) == 1
        assert len(standalones) == 1
        assert standalones[0].layer_id == "l-2"
        assert standalones[0].reason == "render_standalone"

    def test_same_input_produces_same_bundle_id(self):
        layers = [
            _layer(layer_id="l-1", geoserver_layer_name="pg:a", object_class="DEPARE"),
            _layer(layer_id="l-2", geoserver_layer_name="pg:b", object_class="SEAARE"),
        ]
        b1, _ = build_bundles(layers, "core_chart", "EPSG:3857")
        b2, _ = build_bundles(layers, "core_chart", "EPSG:3857")
        assert b1[0].bundle_id == b2[0].bundle_id
        assert b1[0].cache_key == b2[0].cache_key

    def test_data_version_change_changes_cache_key(self):
        layers = [
            _layer(layer_id="l-1", geoserver_layer_name="pg:a", object_class="DEPARE"),
        ]
        b1, _ = build_bundles(layers, "core_chart", "EPSG:3857", data_version_hash="v1")
        b2, _ = build_bundles(layers, "core_chart", "EPSG:3857", data_version_hash="v2")
        assert b1[0].cache_key != b2[0].cache_key
        # bundle_id should NOT depend on data version (same layers = same grouping)
        assert b1[0].bundle_id == b2[0].bundle_id

    def test_bundle_splits_when_exceeding_max_layers(self):
        layers = [
            _layer(
                layer_id=f"l-{i}",
                geoserver_layer_name=f"pg:layer_{i}",
                object_class="DEPARE",
                display_category="bathymetry",
            )
            for i in range(MAX_LAYERS_PER_BUNDLE + 5)
        ]
        bundles, _ = build_bundles(layers, "core_chart", "EPSG:3857")
        # Should split into at least 2 bundles
        assert len(bundles) >= 2
        # All layers accounted for
        all_ids = [lid for b in bundles for lid in b.layer_ids]
        assert len(all_ids) == len(layers)

    def test_bundles_sorted_by_display_priority_then_object_class(self):
        layers = [
            _layer(layer_id="l-1", object_class="SEAARE", display_priority=10),
            _layer(layer_id="l-2", object_class="DEPARE", display_priority=10),
            _layer(layer_id="l-3", object_class="WRECKS", display_category="hazard", display_priority=40),
            _layer(layer_id="l-4", object_class="OBSTRN", display_category="hazard", display_priority=40),
        ]
        bundles, _ = build_bundles(layers, "core_chart", "EPSG:3857")
        # bathymetry bucket first (sort_order 1), hazard_detail second (sort_order 3)
        assert bundles[0].bucket == "area_fill"
        # Within bucket: DEPARE < SEAARE alphabetically
        assert bundles[0].layer_ids == ["l-2", "l-1"]
        assert bundles[1].bucket == "hazard_detail"
        assert bundles[1].layer_ids == ["l-4", "l-3"]  # OBSTRN < WRECKS

    def test_thirty_layers_produce_reasonable_bundle_count(self):
        """30 logical layers should produce ≤ 6 bundles (not 30 individual)."""
        import random
        random.seed(42)
        categories = [
            ("bathymetry", 10), ("bathymetry", 10),
            ("land_coast", 20), ("land_coast", 20), ("land_coast", 20),
            ("depth", 20),
            ("optional_thematic", 100),
            ("hazard", 40), ("hazard", 40), ("hazard", 40), ("hazard", 40),
            ("navigation_aid", 50), ("navigation_aid", 50),
            ("routing", 60),
            ("restriction_harbor", 70),
            ("optional_thematic", 100),
        ]
        # Create variations — must match len(categories)
        objects = [
            ("DEPARE", "SEAARE"),
            ("COALNE", "LNDARE", "ICEARE"),
            ("DEPCNT",),
            ("WRECKS", "OBSTRN", "UWTROC", "CTNARE"),
            ("LIGHTS", "FOGSIG"),
            ("TSSBND",),
            ("RESARE",),
            ("ADMARE", "SOUNDG"),
            ("DEPARE", "SEAARE"),
            ("COALNE", "LNDARE", "ICEARE"),
            ("DEPCNT",),
            ("WRECKS", "OBSTRN", "UWTROC", "CTNARE"),
            ("LIGHTS", "FOGSIG"),
            ("TSSBND",),
            ("RESARE",),
            ("ADMARE",),
        ]
        layers = []
        for i in range(30):
            cat_idx = i % len(categories)
            cat, pri = categories[cat_idx]
            objs = objects[cat_idx]
            obj = objs[i % len(objs)]
            layers.append(
                _layer(
                    layer_id=f"l-{i:03d}",
                    geoserver_layer_name=f"pg:l_{i:03d}",
                    style_name=f"pg:s_{obj.lower()}",
                    object_class=obj,
                    display_category=cat,
                    display_priority=pri,
                )
            )
        bundles, standalones = build_bundles(layers, "all_spatial", "EPSG:3857")
        assert len(bundles) <= 6  # not 30 individual layers
        assert len(bundles) >= 2  # multiple buckets
        all_ids = {lid for b in bundles for lid in b.layer_ids}
        # All 30 layers should be in bundles (no standalones since all default opacity)
        assert len(all_ids) == 30
        assert len(standalones) == 0

    def test_empty_layers_returns_empty(self):
        bundles, standalones = build_bundles([], "core_chart", "EPSG:3857")
        assert bundles == []
        assert standalones == []


# ── bundle_cache_key ───────────────────────────────────────────────────────

class TestBundleCacheKey:
    def test_deterministic_for_same_input(self):
        k1 = bundle_cache_key("bucket-a", ["pg:a", "pg:b"], "EPSG:3857")
        k2 = bundle_cache_key("bucket-a", ["pg:a", "pg:b"], "EPSG:3857")
        assert k1 == k2

    def test_different_for_different_buckets(self):
        k1 = bundle_cache_key("area_fill", ["pg:a"], "EPSG:3857")
        k2 = bundle_cache_key("line_structure", ["pg:a"], "EPSG:3857")
        assert k1 != k2

    def test_order_independent_for_layer_names(self):
        """Cache key should be order-independent (sorted internally)."""
        k1 = bundle_cache_key("area_fill", ["pg:a", "pg:b"], "EPSG:3857")
        k2 = bundle_cache_key("area_fill", ["pg:b", "pg:a"], "EPSG:3857")
        assert k1 == k2


# ── compute_bundle_id ──────────────────────────────────────────────────────

class TestComputeBundleId:
    def test_same_layers_same_id(self):
        id1 = compute_bundle_id("area_fill", ["pg:a", "pg:b"], "EPSG:3857")
        id2 = compute_bundle_id("area_fill", ["pg:a", "pg:b"], "EPSG:3857")
        assert id1 == id2

    def test_different_bucket_different_id(self):
        id1 = compute_bundle_id("area_fill", ["pg:a"], "EPSG:3857")
        id2 = compute_bundle_id("line_structure", ["pg:a"], "EPSG:3857")
        assert id1 != id2

    def test_contains_bucket_and_hash(self):
        bundle_id = compute_bundle_id("area_fill", ["pg:a", "pg:b"], "EPSG:3857")
        assert bundle_id.startswith("area_fill:")
        # 8-char hex hash after colon
        parts = bundle_id.split(":")
        assert len(parts) == 2
        assert len(parts[1]) == 8


# ── BundleConfig immutable ─────────────────────────────────────────────────

class TestBundleConfig:
    def test_frozen_dataclass(self):
        config = BundleConfig(
            bundle_id="area_fill:abc12345",
            bucket="area_fill",
            layer_ids=["l-1", "l-2"],
            layer_names=["pg:a", "pg:b"],
            styles=["pg:sa", "pg:sb"],
            z_index=10,
            opacity=1.0,
            extent=None,
            min_zoom=None,
            max_zoom=None,
            transport="wms_multi",
            service_url="/geoserver/pg/wms",
            cache_key="sha256hash",
        )
        with pytest.raises(FrozenInstanceError):
            config.bucket = "changed"  # type: ignore[misc]


# ── LayerRenderInput ───────────────────────────────────────────────────────

class TestLayerRenderInput:
    def test_default_opacity_is_one(self):
        layer = _layer()
        assert layer.opacity == 1.0

    def test_render_standalone_defaults_false(self):
        layer = _layer()
        assert layer.render_standalone is False
