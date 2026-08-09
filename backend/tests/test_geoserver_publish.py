"""Tests for GeoServer feature-type publish payloads with optional data bounds.

Captures the JSON payloads sent to the REST API via a stub ``_request``, so
assertions verify exactly what GeoServer receives for ``nativeBoundingBox`` /
``latLonBoundingBox``.
"""

import httpx
import pytest

from app.core.config import Settings
from app.services.geoserver import GeoServerClient

GLOBAL_BBOX = {
    "minx": -180,
    "maxx": 180,
    "miny": -90,
    "maxy": 90,
    "crs": "EPSG:4326",
}


class CapturingGeoServerClient(GeoServerClient):
    """GeoServerClient stand-in that captures feature-type publish payloads."""

    def __init__(self) -> None:
        super().__init__(Settings())
        self.published_payloads: list[dict] = []

    def _request(
        self,
        method: str,
        path: str,
        allowed_statuses: set[int] | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        if method == "POST" and "featuretypes" in path:
            payload = kwargs.get("json")
            if isinstance(payload, dict):
                self.published_payloads.append(payload)
        return httpx.Response(201, json={})


class TestPublishFeatureTypeBounds:
    def test_bounds_fill_native_and_latlon_bbox(self) -> None:
        client = CapturingGeoServerClient()
        client.publish_feature_type(
            "ds_1_depare",
            "depare_layer",
            "DEPARE",
            bounds=[-15.0, 62.0, 30.0, 81.0],
        )
        assert len(client.published_payloads) == 1
        feature_type = client.published_payloads[0]["featureType"]
        expected = {
            "minx": -15.0,
            "maxx": 30.0,
            "miny": 62.0,
            "maxy": 81.0,
            "crs": "EPSG:4326",
        }
        assert feature_type["nativeBoundingBox"] == expected
        assert feature_type["latLonBoundingBox"] == expected

    def test_default_none_keeps_global_bounds(self) -> None:
        client = CapturingGeoServerClient()
        client.publish_feature_type("ds_1_depare", "depare_layer", "DEPARE")
        assert len(client.published_payloads) == 1
        feature_type = client.published_payloads[0]["featureType"]
        assert feature_type["nativeBoundingBox"] == GLOBAL_BBOX
        assert feature_type["latLonBoundingBox"] == GLOBAL_BBOX


class TestPublishFeatureTypesBatchBounds:
    def test_per_spec_bounds_used_and_batch_param_as_fallback(self) -> None:
        client = CapturingGeoServerClient()
        client.publish_feature_types_batch(
            [
                {
                    "table_name": "ds_1_depare",
                    "layer_name": "depare",
                    "title": "DEPARE",
                    "bounds": [1.0, 2.0, 3.0, 4.0],
                },
                {
                    "table_name": "ds_1_lights",
                    "layer_name": "lights",
                    "title": "LIGHTS",
                },
            ],
            bounds=[-10.0, 50.0, 20.0, 70.0],
        )
        assert len(client.published_payloads) == 2
        with_bounds = client.published_payloads[0]["featureType"]
        assert with_bounds["nativeBoundingBox"] == {
            "minx": 1.0,
            "maxx": 3.0,
            "miny": 2.0,
            "maxy": 4.0,
            "crs": "EPSG:4326",
        }
        assert with_bounds["latLonBoundingBox"] == with_bounds["nativeBoundingBox"]
        fallback = client.published_payloads[1]["featureType"]
        assert fallback["nativeBoundingBox"] == {
            "minx": -10.0,
            "maxx": 20.0,
            "miny": 50.0,
            "maxy": 70.0,
            "crs": "EPSG:4326",
        }
        assert fallback["latLonBoundingBox"] == fallback["nativeBoundingBox"]

    def test_spec_bounds_override_batch_param(self) -> None:
        client = CapturingGeoServerClient()
        client.publish_feature_types_batch(
            [
                {
                    "table_name": "ds_1_depare",
                    "layer_name": "depare",
                    "title": "DEPARE",
                    "bounds": [1.0, 2.0, 3.0, 4.0],
                }
            ],
            bounds=[-10.0, 50.0, 20.0, 70.0],
        )
        feature_type = client.published_payloads[0]["featureType"]
        assert feature_type["nativeBoundingBox"]["minx"] == 1.0

    def test_no_bounds_keeps_global_for_all(self) -> None:
        client = CapturingGeoServerClient()
        client.publish_feature_types_batch(
            [
                {"table_name": "ds_1_depare", "layer_name": "depare", "title": "DEPARE"},
                {"table_name": "ds_1_lights", "layer_name": "lights", "title": "LIGHTS"},
            ]
        )
        assert len(client.published_payloads) == 2
        for payload in client.published_payloads:
            feature_type = payload["featureType"]
            assert feature_type["nativeBoundingBox"] == GLOBAL_BBOX
            assert feature_type["latLonBoundingBox"] == GLOBAL_BBOX


class TestInvalidBoundsFallback:
    @pytest.mark.parametrize(
        "bad_bounds",
        [
            [10.0, 0.0, 5.0, 10.0],  # minx >= maxx
            [1.0, 8.0, 3.0, 4.0],  # miny >= maxy
            [float("nan"), 0.0, 5.0, 10.0],  # non-finite
            [float("inf"), 0.0, 5.0, 10.0],  # non-finite
            [1.0, 2.0, 3.0],  # wrong length
            ["a", 0.0, 5.0, 10.0],  # non-numeric
            [1.0, 2.0, 3.0, None],  # non-numeric
            "not-a-list",  # wrong type
            {"minx": 1.0, "maxx": 3.0},  # wrong type
        ],
    )
    def test_invalid_bounds_fall_back_to_global(self, bad_bounds: object) -> None:
        client = CapturingGeoServerClient()
        client.publish_feature_type(
            "ds_1_depare",
            "depare_layer",
            "DEPARE",
            bounds=bad_bounds,  # type: ignore[arg-type]
        )
        feature_type = client.published_payloads[0]["featureType"]
        assert feature_type["nativeBoundingBox"] == GLOBAL_BBOX
        assert feature_type["latLonBoundingBox"] == GLOBAL_BBOX

    def test_invalid_spec_bounds_fall_back_to_global(self) -> None:
        client = CapturingGeoServerClient()
        client.publish_feature_types_batch(
            [
                {
                    "table_name": "ds_1_depare",
                    "layer_name": "depare",
                    "title": "DEPARE",
                    "bounds": [10.0, 0.0, 5.0, 10.0],  # minx >= maxx
                }
            ]
        )
        feature_type = client.published_payloads[0]["featureType"]
        assert feature_type["nativeBoundingBox"] == GLOBAL_BBOX
        assert feature_type["latLonBoundingBox"] == GLOBAL_BBOX
