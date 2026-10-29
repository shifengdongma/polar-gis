"""API tests for navigation environment and vessel endpoints."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from navigation_fixtures import full_fixture_tree

from app.api import navigation_environment
from app.core.config import Settings
from app.navigation.environment.service import EnvironmentService

REQUESTED = "2025-02-15T12:00:00Z"


@pytest.fixture
def synthetic_service(tmp_path: Path) -> EnvironmentService:
    root = tmp_path / "navigation"
    full_fixture_tree(root)
    settings = Settings(
        navigation_data_root=root,
        navigation_ice_data_root=root / "ice",
        navigation_ice_backend="nextsim",
        navigation_manifest_path=root / "navigation_manifest.json",
        ice_data_root=tmp_path / "no-ice",
        planner_result_root=tmp_path / "plans",
    )
    return EnvironmentService(settings)


@pytest.fixture(autouse=True)
def _patch_service(monkeypatch: pytest.MonkeyPatch, synthetic_service: EnvironmentService):
    monkeypatch.setattr(navigation_environment, "get_environment_service", lambda: synthetic_service)
    yield
    synthetic_service.close()


def test_sources_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/navigation/environment/sources").status_code == 401


def test_sources_lists_five_fields(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/navigation/environment/sources", headers=user_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert {item["field"] for item in payload} == {
        "bathymetry",
        "ice",
        "wind",
        "current",
        "wave",
    }
    assert all(item["quality"] == "synthetic" for item in payload)


def test_query_real_only_rejects_synthetic(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/navigation/environment/query",
        headers=user_headers,
        json={
            "longitude": 120.0,
            "latitude": 75.0,
            "time": REQUESTED,
            "fields": ["bathymetry", "wind"],
            "dataPolicy": "real_only",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["fields"]["bathymetry"]["available"] is False
    assert payload["fields"]["bathymetry"]["reason"] == "synthetic_data_not_allowed"
    assert payload["qualitySummary"] == "missing"


def test_query_allow_synthetic_returns_values(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/navigation/environment/query",
        headers=user_headers,
        json={
            "longitude": 120.0,
            "latitude": 75.0,
            "time": REQUESTED,
            "fields": ["bathymetry", "ice", "wind", "current", "wave"],
            "dataPolicy": "allow_synthetic_research",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["fields"]["wind"]["available"] is True
    assert payload["fields"]["wind"]["values"]["speedMs"] == pytest.approx(10.0)
    assert payload["fields"]["wind"]["quality"] == "synthetic"
    assert payload["fields"]["bathymetry"]["values"]["depthM"] == pytest.approx(1500.0)


def test_batch_query_and_field_vectors(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    batch = client.post(
        "/api/v1/navigation/environment/batch-query",
        headers=user_headers,
        json={
            "time": REQUESTED,
            "points": [
                {"id": "p1", "longitude": 120.0, "latitude": 75.0},
                {"id": "p2", "longitude": 121.0, "latitude": 76.0},
            ],
            "fields": ["wind"],
            "dataPolicy": "allow_synthetic_research",
        },
    )
    assert batch.status_code == 200, batch.text
    assert [item["id"] for item in batch.json()["results"]] == ["p1", "p2"]

    field = client.post(
        "/api/v1/navigation/environment/field",
        headers=user_headers,
        json={
            "field": "wind",
            "bbox": [119.0, 74.0, 122.0, 77.0],
            "time": REQUESTED,
            "zoom": 3,
            "maxPoints": 20,
            "dataPolicy": "allow_synthetic_research",
        },
    )
    assert field.status_code == 200, field.text
    payload = field.json()
    assert payload["available"] is True
    assert 4 <= len(payload["points"]) <= 20
    assert payload["points"][0]["available"] is True


def test_bathy_tile_is_public_png(client: TestClient) -> None:
    response = client.get(
        "/api/v1/navigation/environment/tiles/bathymetry/EPSG:3857/0/0/0.png"
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_invalid_field_and_time(client: TestClient, user_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/navigation/environment/query",
        headers=user_headers,
        json={
            "longitude": 120.0,
            "latitude": 75.0,
            "time": "2025-02-15T12:00:00",
            "fields": ["wind"],
        },
    )
    assert response.status_code == 422


def test_navigation_disabled_returns_404(
    client: TestClient,
    user_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(navigation_environment.settings, "navigation_enabled", False)
    response = client.get("/api/v1/navigation/environment/sources", headers=user_headers)
    assert response.status_code == 404
    assert response.json()["code"] == "NAVIGATION_DISABLED"
