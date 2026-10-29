"""API tests for static vessel profiles and depth safety."""

import pytest
from fastapi.testclient import TestClient


def test_vessels_require_auth(client: TestClient) -> None:
    assert client.get("/api/v1/navigation/vessels").status_code == 401


def test_list_and_get_xuelong2(client: TestClient, user_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/navigation/vessels", headers=user_headers)
    assert response.status_code == 200, response.text
    vessels = response.json()
    assert len(vessels) == 1
    vessel = vessels[0]
    assert vessel["id"] == "xuelong2"
    assert vessel["name"] == "雪龙2号"
    assert vessel["designDraftM"] == 7.85
    assert vessel["ukcM"] == 2.0
    assert vessel["requiredDepthM"] == 9.85
    assert vessel["liveStateAvailable"] is False
    assert "未接入实时" in vessel["liveStateNote"]
    assert vessel["sources"]

    detail = client.get("/api/v1/navigation/vessels/xuelong2", headers=user_headers)
    assert detail.status_code == 200
    assert detail.json()["totalPropulsionPowerMw"] == 15.0


def test_depth_safety_safe_and_unsafe(client: TestClient, user_headers: dict[str, str]) -> None:
    safe = client.get(
        "/api/v1/navigation/vessels/xuelong2/depth-safety",
        headers=user_headers,
        params={"depth_m": 10.0},
    )
    assert safe.status_code == 200, safe.text
    assert safe.json()["status"] == "SAFE"
    assert safe.json()["marginM"] == pytest.approx(0.15)

    unsafe = client.get(
        "/api/v1/navigation/vessels/xuelong2/depth-safety",
        headers=user_headers,
        params={"depth_m": 9.0},
    )
    assert unsafe.status_code == 200
    assert unsafe.json()["status"] == "UNSAFE"
    assert unsafe.json()["reason"] == "insufficient_under_keel_clearance"


def test_unknown_vessel_404(client: TestClient, user_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/navigation/vessels/not-a-vessel", headers=user_headers)
    assert response.status_code == 404
    assert response.json()["code"] == "VESSEL_NOT_FOUND"
