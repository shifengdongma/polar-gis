"""IceService 单元测试。

硬性约束(与本文件相配套的实现契约):
- 全部 NetCDF fixture 均在本用例的 tmp_path 内动态生成,绝不提交大样例数据;
- 数值断言基于「小网格 + 已知值」自行推导,不复刻实现内部结构;
- NoData 语义按任务书:concentration 0 有效、127/>100/<0/NaN 均 NoData;
  thickness mask/哨兵均 NoData,cm→m、mm→m、未知单位不换算。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from netCDF4 import Dataset
from pyproj import Transformer

from app.core.errors import AppError
from app.services.ice import (
    PALETTE_STOPS,
    IceService,
)

# 以极点附近 ~±2000km 的 3411 网格作为 fixture 坐标(覆盖大范围,瓦片采样稳定)
GRID_X = np.arange(-2_000_000.0, 2_000_001.0, 250_000.0)
GRID_Y = np.arange(-2_000_000.0, 2_000_001.0, 250_000.0)


def write_nc(
    path: Path,
    values: np.ndarray | None = None,
    *,
    var_name: str = "sic_merged",
    units: str | None = None,
    dtype: str = "f4",
    fill_value: float | None = None,
    x: np.ndarray | None = None,
    y: np.ndarray | None = None,
) -> Path:
    """写入一个最小 NetCDF:1-D x/y 坐标 + 单个二维场变量。"""
    x = GRID_X if x is None else x
    y = GRID_Y if y is None else y
    if values is None:
        values = np.full((len(y), len(x)), 50.0)
    ds = Dataset(str(path), "w")
    try:
        ds.createDimension("y", len(y))
        ds.createDimension("x", len(x))
        xv = ds.createVariable("x", "f8", ("x",))
        xv[:] = x
        xv.units = "m"
        yv = ds.createVariable("y", "f8", ("y",))
        yv[:] = y
        yv.units = "m"
        kwargs: dict[str, object] = {}
        if fill_value is not None:
            kwargs["fill_value"] = fill_value
        variable = ds.createVariable(var_name, dtype, ("y", "x"), **kwargs)
        variable[:] = values.astype(dtype)
        if units is not None:
            variable.units = units
    finally:
        ds.close()
    return path


def center_of(values: np.ndarray) -> tuple[float, float]:
    """网格中心点的 3411 坐标(fixture 网格对称,中心即 (0,0) 附近)。"""
    return float(GRID_X[len(GRID_X) // 2]), float(GRID_Y[len(GRID_Y) // 2])


def to_display(x: float, y: float, crs: str) -> tuple[float, float]:
    return Transformer.from_crs("EPSG:3411", crs, always_xy=True).transform(x, y)


def read_png_alpha(png: bytes) -> np.ndarray:
    from io import BytesIO

    from PIL import Image

    image = Image.open(BytesIO(png))
    return np.asarray(image)[..., 3]


# ── 1. 空目录与降级 ─────────────────────────────────────────────────────


def test_empty_dir_returns_empty_info(tmp_path: Path) -> None:
    service = IceService(tmp_path)
    assert service.dates == []
    assert service.info() == {"dates": [], "fields": [], "default_date": None}
    # 空目录下所有查询都不抛异常(降级原则:Ice failure != Map failure)
    assert service.value_at("20220101", 0, 0, "EPSG:3413") is None


def test_empty_dir_tile_raises_date_not_found(tmp_path: Path) -> None:
    service = IceService(tmp_path)
    with pytest.raises(AppError) as excinfo:
        service.tile("concentration", "EPSG:3413", "20220101", 0, 0, 0)
    assert excinfo.value.status_code == 404
    assert excinfo.value.code == "ICE_DATE_NOT_FOUND"


def test_missing_root_dir_is_tolerated(tmp_path: Path) -> None:
    service = IceService(tmp_path / "does-not-exist")
    assert service.dates == []
    assert service.info()["dates"] == []


def test_corrupt_file_degrades_without_crash(tmp_path: Path) -> None:
    (tmp_path / "broken_20220101.nc").write_bytes(b"not a netcdf file at all")
    write_nc(tmp_path / "good_20220102.nc", np.full((len(GRID_Y), len(GRID_X)), 60.0))
    service = IceService(tmp_path)
    info = service.info()
    assert info["dates"] == ["20220101", "20220102"]
    # 损坏日期不计入字段可用日期;完好日期正常
    concentration = next(f for f in info["fields"] if f["id"] == "concentration")
    assert concentration["available_dates"] == ["20220102"]
    # 损坏日期的查询优雅返回
    assert service.value_at("20220101", 0, 0, "EPSG:3413") is None
    with pytest.raises(AppError):
        service.tile("concentration", "EPSG:3413", "20220101", 0, 0, 0)


# ── 2. 日期识别与排序 ────────────────────────────────────────────────────


def test_date_discovery_and_sort(tmp_path: Path) -> None:
    for day in ("20220103", "20220101", "20220129"):
        write_nc(tmp_path / f"prefix_{day}.nc")
    # 不匹配的文件名一律忽略(末尾必须是 8 位日期)
    write_nc(tmp_path / "no_date_here.nc")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    service = IceService(tmp_path)
    assert service.dates == ["20220101", "20220103", "20220129"]


# ── 3/4/5. 字段别名与跨日期并集 ─────────────────────────────────────────


def test_field_alias_detection(tmp_path: Path) -> None:
    write_nc(tmp_path / "a_20220101.nc", var_name="sea_ice_area_fraction")
    write_nc(tmp_path / "b_20220102.nc", var_name="sea_ice_thickness", units="m")
    info = IceService(tmp_path).info()
    ids = {f["id"] for f in info["fields"]}
    assert ids == {"concentration", "thickness"}


def test_info_field_union_across_dates(tmp_path: Path) -> None:
    write_nc(tmp_path / "a_20220101.nc", var_name="sic_merged")
    ds_path = tmp_path / "b_20220105.nc"
    write_nc(ds_path, var_name="sic_merged")
    # 第二个日期额外写入厚度变量
    ds = Dataset(str(ds_path), "a")
    variable = ds.createVariable("sea_ice_thickness", "f4", ("y", "x"))
    variable[:] = np.full((len(GRID_Y), len(GRID_X)), 1.5)
    variable.units = "m"
    ds.close()

    info = IceService(tmp_path).info()
    assert info["dates"] == ["20220101", "20220105"]
    assert info["default_date"] == "20220101"
    by_id = {f["id"]: f for f in info["fields"]}
    assert by_id["concentration"]["available_dates"] == ["20220101", "20220105"]
    assert by_id["thickness"]["available_dates"] == ["20220105"]
    assert by_id["thickness"]["units"] == "m"
    assert by_id["concentration"]["label"] == "海冰浓度"
    assert info["source_crs"] == "EPSG:3411"
    assert info["extent"] == [
        float(GRID_X[0]),
        float(GRID_Y[0]),
        float(GRID_X[-1]),
        float(GRID_Y[-1]),
    ]


# ── 6. concentration NoData 语义 ────────────────────────────────────────


def test_concentration_zero_is_valid(tmp_path: Path) -> None:
    values = np.full((len(GRID_Y), len(GRID_X)), 0.0)
    write_nc(tmp_path / "z_20220101.nc", values, var_name="sic_merged", dtype="i1")
    service = IceService(tmp_path)
    x, y = center_of(values)
    result = service.value_at("20220101", *to_display(x, y, "EPSG:3413"), "EPSG:3413")
    assert result is not None
    assert result["value"] == 0.0  # 0% 是有效值,不得当作 NoData


@pytest.mark.parametrize("nodata", [127.0, 101.0, 255.0, -5.0, float("nan")])
def test_concentration_out_of_range_is_nodata(tmp_path: Path, nodata: float) -> None:
    values = np.full((len(GRID_Y), len(GRID_X)), 50.0)
    values[len(GRID_Y) // 2, len(GRID_X) // 2] = nodata
    write_nc(tmp_path / "n_20220101.nc", values, var_name="sic_merged", dtype="f4")
    service = IceService(tmp_path)
    x, y = center_of(values)
    result = service.value_at("20220101", *to_display(x, y, "EPSG:3413"), "EPSG:3413")
    assert result is None


def test_concentration_domain_is_fixed_regardless_of_units_attr(tmp_path: Path) -> None:
    # 真实数据 units 缺失/为 Percentage,域恒为 0-100,不做单位猜测
    values = np.full((len(GRID_Y), len(GRID_X)), 50.0)
    write_nc(tmp_path / "u_20220101.nc", values, var_name="sic_merged", units="Percentage")
    service = IceService(tmp_path)
    x, y = center_of(values)
    result = service.value_at("20220101", *to_display(x, y, "EPSG:3413"), "EPSG:3413")
    assert result is not None
    assert result["value"] == 50.0
    assert result["units"] == "%"


# ── 7/8/9. thickness 单位换算与哨兵 ─────────────────────────────────────


def test_thickness_cm_to_m(tmp_path: Path) -> None:
    values = np.full((len(GRID_Y), len(GRID_X)), 150.0)
    write_nc(tmp_path / "t_20220101.nc", values, var_name="sea_ice_thickness", units="cm")
    service = IceService(tmp_path)
    x, y = center_of(values)
    result = service.value_at("20220101", *to_display(x, y, "EPSG:3413"), "EPSG:3413", "thickness")
    assert result is not None
    assert result["value"] == pytest.approx(1.5)
    assert result["units"] == "m"


def test_thickness_mm_to_m(tmp_path: Path) -> None:
    values = np.full((len(GRID_Y), len(GRID_X)), 2500.0)
    write_nc(tmp_path / "t_20220101.nc", values, var_name="sea_ice_thickness", units="mm")
    service = IceService(tmp_path)
    x, y = center_of(values)
    result = service.value_at("20220101", *to_display(x, y, "EPSG:3413"), "EPSG:3413", "thickness")
    assert result is not None
    assert result["value"] == pytest.approx(2.5)


def test_thickness_unknown_units_pass_through_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    values = np.full((len(GRID_Y), len(GRID_X)), 3.0)
    write_nc(tmp_path / "t_20220101.nc", values, var_name="sea_ice_thickness", units="furlongs")
    service = IceService(tmp_path)
    x, y = center_of(values)
    with caplog.at_level(logging.WARNING, logger="polar_gis.ice"):
        result = service.value_at(
            "20220101", *to_display(x, y, "EPSG:3413"), "EPSG:3413", "thickness"
        )
    assert result is not None
    assert result["value"] == pytest.approx(3.0)  # 未知单位不换算、不猜测
    assert any("units" in record.message.lower() or "单位" in record.message for record in caplog.records)


def test_thickness_fill_sentinel_is_nodata(tmp_path: Path) -> None:
    # 参考实现缺陷回归:masked/哨兵值绝不能以 9.97e36 这样的"有限大数"进入渲染
    sentinel = 9.96921e36
    values = np.full((len(GRID_Y), len(GRID_X)), 2.0)
    values[len(GRID_Y) // 2, len(GRID_X) // 2] = sentinel
    write_nc(
        tmp_path / "t_20220101.nc",
        values,
        var_name="sea_ice_thickness",
        units="m",
        dtype="f4",
        fill_value=sentinel,
    )
    service = IceService(tmp_path)
    x, y = center_of(values)
    result = service.value_at("20220101", *to_display(x, y, "EPSG:3413"), "EPSG:3413", "thickness")
    assert result is None


# ── 10. 瓦片渲染 ────────────────────────────────────────────────────────


def test_tile_3413_renders_data_and_outside_tile_is_transparent(tmp_path: Path) -> None:
    values = np.full((len(GRID_Y), len(GRID_X)), 100.0)
    write_nc(tmp_path / "c_20220101.nc", values, var_name="sic_merged")
    service = IceService(tmp_path)
    png = service.tile("concentration", "EPSG:3413", "20220101", 2, 2, 2)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    alpha = read_png_alpha(png)
    assert int((alpha > 0).sum()) > 0  # 网格覆盖瓦片区域 → 有非透明像素

    # 远离数据范围的瓦片应全透明
    far = service.tile("concentration", "EPSG:3413", "20220101", 2, 0, 3)
    assert int((read_png_alpha(far) > 0).sum()) == 0


def test_tile_3857_renders_and_clamps_pole(tmp_path: Path) -> None:
    values = np.full((len(GRID_Y), len(GRID_X)), 100.0)
    write_nc(tmp_path / "c_20220101.nc", values, var_name="sic_merged")
    service = IceService(tmp_path)
    # 3857 z0 单瓦片覆盖全球:极点上方区域(±85.05° 以外)必须透明,
    # 而北冰洋区域有数据。整幅图上透明与不透明像素并存。
    png = service.tile("concentration", "EPSG:3857", "20220101", 0, 0, 0)
    alpha = read_png_alpha(png)
    assert int((alpha > 0).sum()) > 0
    assert int((alpha == 0).sum()) > 0


def test_tile_zero_value_is_transparent(tmp_path: Path) -> None:
    write_nc(tmp_path / "z_20220101.nc", np.zeros((len(GRID_Y), len(GRID_X))))
    service = IceService(tmp_path)
    png = service.tile("concentration", "EPSG:3413", "20220101", 2, 2, 2)
    assert int((read_png_alpha(png) > 0).sum()) == 0  # 0% 完全透明(但仍可 hover 到 0)


def test_tile_invalid_inputs_raise_app_error(tmp_path: Path) -> None:
    write_nc(tmp_path / "c_20220101.nc")
    service = IceService(tmp_path, max_zoom=3)

    with pytest.raises(AppError) as e1:
        service.tile("temperature", "EPSG:3413", "20220101", 0, 0, 0)
    assert e1.value.code == "ICE_FIELD_INVALID"

    with pytest.raises(AppError) as e2:
        service.tile("concentration", "EPSG:1234", "20220101", 0, 0, 0)
    assert e2.value.code == "ICE_PROJECTION_INVALID"

    with pytest.raises(AppError) as e3:
        service.tile("concentration", "EPSG:3413", "20220101", 4, 0, 0)
    assert e3.value.code == "ICE_TILE_COORD_INVALID"

    with pytest.raises(AppError) as e4:
        service.tile("concentration", "EPSG:3413", "20220101", 2, 4, 0)
    assert e4.value.code == "ICE_TILE_COORD_INVALID"

    with pytest.raises(AppError) as e5:
        service.tile("concentration", "EPSG:3413", "20990101", 0, 0, 0)
    assert e5.value.code == "ICE_DATE_NOT_FOUND"

    with pytest.raises(AppError) as e6:
        service.tile("thickness", "EPSG:3413", "20220101", 0, 0, 0)
    assert e6.value.code == "ICE_FIELD_UNAVAILABLE"


# ── 11. value_at 细节 ───────────────────────────────────────────────────


def test_value_at_returns_raw_grid_value_for_both_projections(tmp_path: Path) -> None:
    values = np.full((len(GRID_Y), len(GRID_X)), 63.0)
    write_nc(tmp_path / "c_20220101.nc", values)
    service = IceService(tmp_path)

    # 极点(3411 原点)——仅 3413 可表示并正确命中;3857 按设计拒绝(见 miss 用例)
    cx, cy = center_of(values)
    dx, dy = to_display(cx, cy, "EPSG:3413")
    pole_result = service.value_at("20220101", dx, dy, "EPSG:3413")
    assert pole_result is not None
    assert pole_result["value"] == 63.0

    # 双投影共同可用的网点(lat < 85.05112878°,Web 墨卡托可表示)
    for crs in ("EPSG:3413", "EPSG:3857"):
        x, y = 1_500_000.0, 1_500_000.0
        dx, dy = to_display(x, y, crs)
        result = service.value_at("20220101", dx, dy, crs)
        assert result is not None, crs
        assert result["value"] == 63.0
        assert result["date"] == "20220101"
        assert result["field"] == "concentration"
        assert result["units"] == "%"
        assert isinstance(result["longitude"], float)
        assert isinstance(result["latitude"], float)
        assert result["source_x"] == pytest.approx(x, abs=1.0)
        assert result["source_y"] == pytest.approx(y, abs=1.0)


def test_value_at_miss_cases(tmp_path: Path) -> None:
    write_nc(tmp_path / "c_20220101.nc")
    service = IceService(tmp_path)
    assert service.value_at("20990101", 0, 0, "EPSG:3413") is None  # 不存在日期
    assert service.value_at("20220101", float("nan"), 0, "EPSG:3413") is None
    assert service.value_at("20220101", 1e9, 1e9, "EPSG:3413") is None  # 数据范围之外
    assert service.value_at("20220101", 0, 0, "EPSG:9999") is None  # 不支持投影
    # 3857 极点上方(>85.05112878°)不可表示 → None
    pole_x = 0.0
    pole_y = 30_000_000.0  # 远超 3857 有效纬度对应 y
    assert service.value_at("20220101", pole_x, pole_y, "EPSG:3857") is None


def test_value_at_handles_descending_axes(tmp_path: Path) -> None:
    values = np.full((len(GRID_Y), len(GRID_X)), 42.0)
    write_nc(
        tmp_path / "c_20220101.nc",
        values,
        x=GRID_X[::-1].copy(),
        y=GRID_Y[::-1].copy(),
    )
    service = IceService(tmp_path)
    x, y = center_of(values)
    result = service.value_at("20220101", *to_display(x, y, "EPSG:3413"), "EPSG:3413")
    assert result is not None
    assert result["value"] == 42.0


# ── 12. alignment ───────────────────────────────────────────────────────


def test_alignment_geojson_control_points(tmp_path: Path) -> None:
    write_nc(tmp_path / "c_20220101.nc", np.full((len(GRID_Y), len(GRID_X)), 87.0))
    service = IceService(tmp_path)
    geojson = service.alignment_geojson("20220101", "EPSG:3413")
    assert geojson["type"] == "FeatureCollection"
    assert 1 <= len(geojson["features"]) <= 5
    for feature in geojson["features"]:
        assert feature["geometry"]["type"] == "Point"
        assert len(feature["geometry"]["coordinates"]) == 2
        assert feature["properties"]["raw_value"] == 87
    assert geojson["crs"]["properties"]["name"] == "EPSG:3413"


def test_alignment_unknown_date_raises(tmp_path: Path) -> None:
    service = IceService(tmp_path)
    with pytest.raises(AppError) as excinfo:
        service.alignment_geojson("20990101", "EPSG:3413")
    assert excinfo.value.code == "ICE_DATE_NOT_FOUND"


# ── 13. 缓存语义 ────────────────────────────────────────────────────────


def test_tile_cache_returns_identical_bytes_and_survives_eviction(tmp_path: Path) -> None:
    write_nc(tmp_path / "c_20220101.nc", np.full((len(GRID_Y), len(GRID_X)), 75.0))
    service = IceService(tmp_path, tile_cache_entries=1)  # 极小缓存强制驱逐
    first = service.tile("concentration", "EPSG:3413", "20220101", 2, 2, 2)
    second = service.tile("concentration", "EPSG:3413", "20220101", 2, 2, 2)
    assert first == second  # 缓存命中/驱逐都不得改变结果
    service.tile("concentration", "EPSG:3413", "20220101", 2, 3, 2)  # 触发驱逐
    third = service.tile("concentration", "EPSG:3413", "20220101", 2, 2, 2)
    assert third == first


# ── 14. 文件索引刷新与失效 ──────────────────────────────────────────────


def test_info_refresh_picks_up_new_dates(tmp_path: Path) -> None:
    write_nc(tmp_path / "a_20220101.nc")
    service = IceService(tmp_path)
    assert service.dates == ["20220101"]
    write_nc(tmp_path / "b_20220102.nc")
    info = service.info()  # info 触发重扫
    assert info["dates"] == ["20220101", "20220102"]


def test_replaced_file_invalidates_cached_values(tmp_path: Path) -> None:
    path = tmp_path / "c_20220101.nc"
    write_nc(path, np.full((len(GRID_Y), len(GRID_X)), 10.0))
    service = IceService(tmp_path)
    x, y = center_of(np.zeros((len(GRID_Y), len(GRID_X))))
    dx, dy = to_display(x, y, "EPSG:3413")
    assert service.value_at("20220101", dx, dy, "EPSG:3413")["value"] == 10.0

    write_nc(path, np.full((len(GRID_Y), len(GRID_X)), 80.0), fill_value=999.0)
    os.utime(path, (os.path.getmtime(path) + 5, os.path.getmtime(path) + 5))
    service.info()  # 重扫 → 该日期 (mtime,size) 变化 → 缓存失效
    assert service.value_at("20220101", dx, dy, "EPSG:3413")["value"] == 80.0


# ── 15. 调色板锁定(与前端 mapIce.ts 常量逐值一致) ──────────────────────


def test_palette_stops_are_locked() -> None:
    stops, colors = PALETTE_STOPS["concentration"]
    assert stops == [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    assert colors[0] == (218, 246, 249, 0)  # 0% alpha = 0
    assert colors[5] == (25, 94, 145, 225)
    assert colors[10] == (171, 36, 66, 250)
    thickness_stops, thickness_colors = PALETTE_STOPS["thickness"]
    assert thickness_stops == [0.0, 0.5, 1.5, 3.0, 5.0]
    assert thickness_colors[0] == (255, 246, 214, 0)
    assert thickness_colors[-1] == (142, 36, 95, 250)


# ── 16. 并发单飞与预热(瓦片请求堆积的根因回归防护) ─────────────────────


def test_concurrent_grid_loads_are_single_flight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一冷日期的并发网格装载只允许真正读文件一次(惊群回归守卫)。

    回归背景:归一化在锁外执行期间缓存未落盘,并发首请求会各自完整装载
    26M 单元网格 —— 实测 8 张冷瓦片每张 6.6s(应为 1 次装载 + N 次渲染)。
    """
    write_nc(tmp_path / "c_20220101.nc", np.full((len(GRID_Y), len(GRID_X)), 50.0))
    service = IceService(tmp_path)

    calls: list[str] = []
    calls_lock = threading.Lock()
    original = IceService._normalize

    def counting_normalize(self: IceService, field: str, raw: np.ndarray, units: str, x: np.ndarray, y: np.ndarray):
        with calls_lock:
            calls.append(field)
        time.sleep(0.2)  # 放大竞态窗口:没有单飞时并发线程会全部重复装载
        return original(self, field, raw, units, x, y)

    monkeypatch.setattr(IceService, "_normalize", counting_normalize)

    with ThreadPoolExecutor(max_workers=8) as pool:
        grids = list(
            pool.map(lambda _: service._grid("20220101", "concentration"), range(8))
        )

    assert len(calls) == 1, f"网格被重复装载 {len(calls)} 次(应为 1 次单飞装载)"
    assert all(np.array_equal(grid.values, grids[0].values) for grid in grids)


def test_concurrent_tile_requests_load_grid_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """冷日期并发瓦片(公开路径)同样只装载一次网格 —— 8 张瓦片均应成功。"""
    write_nc(tmp_path / "c_20220101.nc", np.full((len(GRID_Y), len(GRID_X)), 80.0))
    service = IceService(tmp_path, tile_cache_entries=64)

    calls: list[str] = []
    calls_lock = threading.Lock()
    original = IceService._normalize

    def counting_normalize(self: IceService, field: str, raw: np.ndarray, units: str, x: np.ndarray, y: np.ndarray):
        with calls_lock:
            calls.append(field)
        time.sleep(0.2)
        return original(self, field, raw, units, x, y)

    monkeypatch.setattr(IceService, "_normalize", counting_normalize)

    def load(tx: int) -> bytes:
        return service.tile("concentration", "EPSG:3413", "20220101", 3, tx, 2)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(load, range(8)))

    assert len(calls) == 1
    assert all(png[:8] == b"\x89PNG\r\n\x1a\n" for png in results)


def test_warm_default_grid_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """warm_default_grid 预载默认日期网格;重复调用命中缓存不再装载。"""
    write_nc(tmp_path / "a_20220101.nc", np.full((len(GRID_Y), len(GRID_X)), 60.0))
    write_nc(tmp_path / "b_20220102.nc")
    service = IceService(tmp_path)

    calls: list[str] = []
    original = IceService._normalize

    def counting_normalize(self: IceService, field: str, raw: np.ndarray, units: str, x: np.ndarray, y: np.ndarray):
        calls.append(field)
        return original(self, field, raw, units, x, y)

    monkeypatch.setattr(IceService, "_normalize", counting_normalize)

    service.warm_default_grid()  # 默认日期 = 最早日期(dates[0])
    assert len(calls) == 1
    service.warm_default_grid()  # 已缓存 → 不重复装载
    assert len(calls) == 1
    # 空目录安全
    IceService(tmp_path / "empty").warm_default_grid()


def test_info_triggers_background_warm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """info() 会在后台线程预热默认日期网格(不阻塞响应)。"""
    write_nc(tmp_path / "a_20220101.nc", np.full((len(GRID_Y), len(GRID_X)), 60.0))
    service = IceService(tmp_path)

    warmed: list[bool] = []
    monkeypatch.setattr(service, "warm_default_grid", lambda: warmed.append(True))

    service.info()
    deadline = time.time() + 2.0
    while not warmed and time.time() < deadline:
        time.sleep(0.01)
    assert warmed == [True]
