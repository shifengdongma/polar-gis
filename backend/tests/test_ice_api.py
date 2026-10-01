"""冰情 API 端点测试。

服务实例经 ``monkeypatch.setattr(ice_api, "get_ice_service", ...)`` 注入
tmp_path 数据(与 test_gwc_backfill 等既有用例同一打补丁惯例);
不依赖开发机数据集、不需要登录(Bearer 也不是必需 —— 冰情路由按地图瓦片
的只读边界设计,OL XYZ <img> 无法携带 Bearer)。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

# pytest prepend 导入模式下 tests/ 在 sys.path 中,可复用服务测试的 fixture 写盘工具
from test_ice_service import GRID_X, GRID_Y, write_nc

from app.api import ice as ice_api
from app.core.config import Settings
from app.services.ice import IceService

BASE = "/api/v1/ice"


def install_service(monkeypatch: pytest.MonkeyPatch, root: Path) -> IceService:
    service = IceService(root, tile_cache_entries=8, max_zoom=4)
    monkeypatch.setattr(ice_api, "get_ice_service", lambda: service)
    return service


# ── /info ───────────────────────────────────────────────────────────────


def test_info_no_auth_and_camel_case(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_nc(tmp_path / "sic_20220101.nc", np.full((len(GRID_Y), len(GRID_X)), 55.0))
    install_service(monkeypatch, tmp_path)
    response = client.get(f"{BASE}/info")  # 无 Authorization
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dates"] == ["20220101"]
    assert body["defaultDate"] == "20220101"
    assert body["sourceCrs"] == "EPSG:3411"
    assert body["missingDatesAreExcluded"] is True
    field = body["fields"][0]
    assert field["id"] == "concentration"
    assert field["label"] == "海冰浓度"
    assert field["units"] == "%"
    assert field["availableDates"] == ["20220101"]
    assert isinstance(body["extent"], list) and len(body["extent"]) == 4


def test_info_empty_directory_degrades(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_service(monkeypatch, tmp_path)
    response = client.get(f"{BASE}/info")
    assert response.status_code == 200
    assert response.json() == {"dates": [], "fields": [], "defaultDate": None}


# ── /value ──────────────────────────────────────────────────────────────


def test_value_hit_returns_camel_case_payload(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_nc(tmp_path / "sic_20220101.nc", np.full((len(GRID_Y), len(GRID_X)), 63.0))
    install_service(monkeypatch, tmp_path)
    response = client.get(
        f"{BASE}/value",
        params={"date": "20220101", "x": 0.0, "y": 0.0, "projection": "EPSG:3413"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["value"] == 63.0
    assert body["field"] == "concentration"
    assert body["units"] == "%"
    assert "sourceX" in body and "sourceY" in body
    assert "longitude" in body and "latitude" in body


def test_value_miss_is_exactly_value_null(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_nc(tmp_path / "sic_20220101.nc")
    install_service(monkeypatch, tmp_path)
    response = client.get(
        f"{BASE}/value",
        params={"date": "20990101", "x": 0.0, "y": 0.0, "projection": "EPSG:3413"},
    )
    assert response.status_code == 200
    # 精确契约:miss 的响应体只有 {"value": null}(前端以单键判定)
    assert response.json() == {"value": None}


def test_value_malformed_params_422(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_service(monkeypatch, tmp_path)
    bad_date = client.get(f"{BASE}/value", params={"date": "2022", "x": 0, "y": 0})
    assert bad_date.status_code == 422
    bad_projection = client.get(
        f"{BASE}/value",
        params={"date": "20220101", "x": 0, "y": 0, "projection": "EPSG:9999"},
    )
    assert bad_projection.status_code == 422


# ── /{field}/{projection}/tile/{z}/{x}/{y}.png ──────────────────────────


def test_tile_returns_png_with_cache_header(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_nc(tmp_path / "sic_20220101.nc", np.full((len(GRID_Y), len(GRID_X)), 80.0))
    install_service(monkeypatch, tmp_path)
    response = client.get(f"{BASE}/concentration/EPSG:3413/tile/0/0/0.png?date=20220101")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, max-age=300"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_tile_unknown_inputs_404(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_nc(tmp_path / "sic_20220101.nc")
    install_service(monkeypatch, tmp_path)

    unknown_field = client.get(f"{BASE}/temperature/EPSG:3413/tile/0/0/0.png?date=20220101")
    assert unknown_field.status_code == 404
    assert unknown_field.json()["code"] == "ICE_FIELD_INVALID"

    unknown_date = client.get(f"{BASE}/concentration/EPSG:3413/tile/0/0/0.png?date=20990101")
    assert unknown_date.status_code == 404
    assert unknown_date.json()["code"] == "ICE_DATE_NOT_FOUND"

    zoom_too_deep = client.get(f"{BASE}/concentration/EPSG:3413/tile/5/0/0.png?date=20220101")
    assert zoom_too_deep.status_code == 404  # max_zoom=4(服务内校验)
    assert zoom_too_deep.json()["code"] == "ICE_TILE_COORD_INVALID"

    outside = client.get(f"{BASE}/concentration/EPSG:3413/tile/2/9/0.png?date=20220101")
    assert outside.status_code == 404  # x >= 2^z

    missing_var = client.get(f"{BASE}/thickness/EPSG:3413/tile/0/0/0.png?date=20220101")
    assert missing_var.status_code == 404
    assert missing_var.json()["code"] == "ICE_FIELD_UNAVAILABLE"


def test_tile_malformed_params_422(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_service(monkeypatch, tmp_path)
    bad_z = client.get(f"{BASE}/concentration/EPSG:3413/tile/-1/0/0.png?date=20220101")
    assert bad_z.status_code == 422
    bad_projection = client.get(f"{BASE}/concentration/WGS84/tile/0/0/0.png?date=20220101")
    # WGS84 不匹配路由 pattern?路由为 {projection} 段 —— 服务端 404;畸形日期 422
    assert bad_projection.status_code == 404
    bad_date = client.get(f"{BASE}/concentration/EPSG:3413/tile/0/0/0.png?date=abc")
    assert bad_date.status_code == 422


def test_tile_cors_header_present(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_nc(tmp_path / "sic_20220101.nc")
    install_service(monkeypatch, tmp_path)
    response = client.get(
        f"{BASE}/concentration/EPSG:3413/tile/0/0/0.png?date=20220101",
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


# ── /alignment ──────────────────────────────────────────────────────────


def test_alignment_endpoint(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_nc(tmp_path / "sic_20220101.nc", np.full((len(GRID_Y), len(GRID_X)), 87.0))
    install_service(monkeypatch, tmp_path)
    response = client.get(f"{BASE}/alignment", params={"date": "20220101", "projection": "EPSG:3413"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) >= 1

    unknown = client.get(f"{BASE}/alignment", params={"date": "20990101", "projection": "EPSG:3413"})
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "ICE_DATE_NOT_FOUND"


# ── ICE_ENABLED 熔断 ────────────────────────────────────────────────────


def test_ice_disabled_returns_404(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_nc(tmp_path / "sic_20220101.nc")
    install_service(monkeypatch, tmp_path)
    monkeypatch.setattr(ice_api, "settings", Settings(ice_enabled=False))
    response = client.get(f"{BASE}/info")
    assert response.status_code == 404
    assert response.json()["code"] == "ICE_DISABLED"
