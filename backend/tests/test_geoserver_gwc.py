"""Regression tests for GeoWebCache REST paths/payloads (EPSG:3413)."""

from types import SimpleNamespace

from app.core.config import Settings
from app.services import geoserver as geoserver_module
from app.services.geoserver import GeoServerClient


def _client() -> GeoServerClient:
    return GeoServerClient(
        Settings(
            geoserver_url="http://geoserver:8080/geoserver",
            geoserver_admin_user="admin",
            geoserver_admin_password="secret",
        )
    )


def test_ensure_gridset_uses_gwc_rest_xml(monkeypatch):
    calls: list[dict] = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return SimpleNamespace(status_code=200, text="")

    monkeypatch.setattr(geoserver_module.httpx, "request", fake_request)
    _client().ensure_gridset(
        "EPSG:3413",
        "EPSG:3413",
        [-4194304.0, -4194304.0, 4194304.0, 4194304.0],
    )

    assert calls
    call = calls[0]
    assert call["method"] == "PUT"
    assert call["url"] == (
        "http://geoserver:8080/geoserver/gwc/rest/gridsets/EPSG:3413.xml"
    )
    assert call["headers"]["Content-Type"] == "application/xml"
    body = call["content"]
    assert "<gridSet>" in body
    assert "<name>EPSG:3413</name>" in body
    assert "<number>3413</number>" in body
    assert "<double>-4194304.0</double>" in body
    assert "<double>32768.0</double>" in body


def test_ensure_gwc_layer_uses_gwc_rest_xml_and_900913(monkeypatch):
    calls: list[dict] = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return SimpleNamespace(status_code=200, text="")

    monkeypatch.setattr(geoserver_module.httpx, "request", fake_request)
    _client().ensure_gwc_layer("s57_gb1dn000_1_obstrn")

    call = calls[0]
    assert call["method"] == "PUT"
    assert call["url"] == (
        "http://geoserver:8080/geoserver/gwc/rest/layers/"
        "polar_gis:s57_gb1dn000_1_obstrn.xml"
    )
    body = call["content"]
    assert "<GeoServerLayer>" in body
    assert "<autoCacheStyles>true</autoCacheStyles>" in body
    assert "<gridSetName>EPSG:900913</gridSetName>" in body
    assert "<gridSetName>EPSG:4326</gridSetName>" in body
    assert "<gridSetName>EPSG:3413</gridSetName>" in body
    assert "EPSG:3857" not in body


def test_get_gwc_layer_missing_returns_none(monkeypatch):
    monkeypatch.setattr(
        geoserver_module.httpx,
        "request",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=404, text=""),
    )
    assert _client().get_gwc_layer("DEPARE") is None


def test_truncate_and_seed_use_gwc_rest(monkeypatch):
    calls: list[dict] = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return SimpleNamespace(status_code=200, text="")

    monkeypatch.setattr(geoserver_module.httpx, "request", fake_request)
    client = _client()
    client.truncate_layer_cache("DEPARE")
    client.seed_layer_cache("DEPARE")

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "http://geoserver:8080/geoserver/gwc/rest/masstruncate"
    assert "<layerName>polar_gis:DEPARE</layerName>" in calls[0]["content"]
    assert calls[1]["method"] == "POST"
    assert calls[1]["url"] == (
        "http://geoserver:8080/geoserver/gwc/rest/seed/polar_gis:DEPARE.xml"
    )
    assert "<type>seed</type>" in calls[1]["content"]
    assert "<gridSetId>EPSG:900913</gridSetId>" in calls[1]["content"]
