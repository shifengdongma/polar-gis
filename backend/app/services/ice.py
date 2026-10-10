"""冰情数据服务 —— NetCDF 冰场读取与 PNG XYZ 瓦片渲染。

硬性约束:
- 数据目录来自 Settings(``ice_data_root``),代码中绝无机器绝对路径;
- NetCDF 网格坐标系为 ``EPSG:3411``(NSIDC 极射赤面,Hughes 椭球,与 pyproj
  注册定义一致);显示投影 3413/3857 一律**显式经 WGS84 中转**,
  绝不把 3411 米坐标当作 3413;
- 网格坐标必须为 1-D ``x``/``y``(升序/降序均可,内部归一到升序);
- NoData 语义:``concentration`` 有效域 0..100(**0 是有效值**),
  127/101/255/负值/NaN/掩码一律 NoData;``thickness`` 掩码、``_FillValue``、
  ``missing_value`` 哨兵一律 NoData;``cm``→m、``mm``→m,**未知单位不猜测**;
- hover(``value_at``)与瓦片(``_render``)共用同一条网格加载/归一化路径,
  数值不可能漂移;
- 冰情失败 ≠ 地图失败:空目录 / 目录不存在 / 文件损坏一律降级,不抛到调用方
  之外的层。

线程契约:
- 单个 ``RLock`` 只保护 netCDF4 Dataset 访问与缓存变更(HDF5 非线程安全);
- numpy / PIL / pyproj 计算一律在锁外执行;
- pyproj ``Transformer`` 自 3.1 起在内部按线程隔离 PROJ context,可安全跨线程
  共享 —— 不得额外加锁,也不得启用 ``pyproj.set_use_global_context(True)``。
"""

from __future__ import annotations

import logging
import re
import threading
from io import BytesIO
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
from netCDF4 import Dataset
from PIL import Image
from pyproj import Transformer

from app.core.errors import AppError

logger = logging.getLogger("polar_gis.ice")

DATE_RE = re.compile(r"(\d{8})\.nc$", re.I)
SOURCE_CRS = "EPSG:3411"
SUPPORTED_PROJECTIONS = ("EPSG:3413", "EPSG:3857")
MERCATOR_MAX_LAT = 85.05112878
TILE_SIZE = 256

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "concentration": ("sic_merged", "sea_ice_area_fraction", "ice_concentration", "sic"),
    "thickness": ("sea_ice_thickness", "ice_thickness", "sit", "thickness"),
}
FIELD_LABELS = {"concentration": "海冰密集度", "thickness": "海冰厚度"}
FIELD_UNITS = {"concentration": "%", "thickness": "m"}

# 错误码(house style:SCREAMING_SNAKE)
ICE_FIELD_INVALID = "ICE_FIELD_INVALID"
ICE_FIELD_UNAVAILABLE = "ICE_FIELD_UNAVAILABLE"
ICE_DATE_NOT_FOUND = "ICE_DATE_NOT_FOUND"
ICE_PROJECTION_INVALID = "ICE_PROJECTION_INVALID"
ICE_TILE_COORD_INVALID = "ICE_TILE_COORD_INVALID"

# 调色板控制点 —— 真正渲染规则。frontend/src/utils/mapIce.ts 的
# ICE_PALETTES 必须与本表逐值一致(前后端测试各自锁定同一组色值)。
# 0% 与 NoData 的 alpha 均为 0;区间内部按通道线性插值。
PALETTE_STOPS: dict[str, tuple[list[float], list[tuple[int, int, int, int]]]] = {
    "concentration": (
        [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        [
            (218, 246, 249, 0),
            (173, 232, 235, 140),
            (112, 210, 218, 165),
            (51, 180, 195, 190),
            (28, 140, 170, 210),
            (25, 94, 145, 225),
            (242, 207, 103, 230),
            (245, 166, 65, 235),
            (236, 112, 56, 240),
            (213, 64, 57, 245),
            (171, 36, 66, 250),
        ],
    ),
    "thickness": (
        [0.0, 0.5, 1.5, 3.0, 5.0],
        [
            (255, 246, 214, 0),
            (255, 229, 153, 145),
            (239, 155, 70, 210),
            (177, 63, 111, 235),
            (142, 36, 95, 250),
        ],
    ),
}


def _grid_half(projection: str) -> float:
    """瓦片网格半宽(米):3413 与前端 TileGrid extent 严格对齐;3857 为标准墨卡托。"""
    return 4194304.0 if projection == "EPSG:3413" else float(np.pi * 6378137.0)


class _FileEntry(NamedTuple):
    path: Path
    mtime: float
    size: int


class _Grid(NamedTuple):
    x: np.ndarray  # float64,升序
    y: np.ndarray  # float64,升序
    values: np.ndarray  # float32,NaN = NoData,单位 = 上报单位(%, m)
    palette_scale: float  # 上报单位 → 调色板域(concentration 0.01,thickness 1.0)


class IceService:
    """NetCDF 冰场读取 / XYZ 瓦片渲染(线程契约见模块 docstring)。"""

    def __init__(
        self,
        root: Path,
        tile_cache_entries: int = 256,
        max_zoom: int = 10,
    ) -> None:
        self.root = Path(root)
        self._max_zoom = max(int(max_zoom), 0)
        self._tile_cache_entries = max(int(tile_cache_entries), 1)
        self._lock = threading.RLock()
        self._files = self._index_files()
        self._metadata: dict[str, dict[str, Any]] = {}
        self._grids: dict[str, dict[str, _Grid]] = {}
        self._tiles: dict[tuple[str, str, str, int, int, int], bytes] = {}
        self._warned_units: set[str] = set()
        # 单飞(per-date):冷日期并发首请求只允许一个线程真正读文件+归一化,
        # 其余等待 —— 否则 N 张并发瓦片会各自完整装载 26M 单元网格(实测
        # 8 张冷瓦片每张 6.6s;单飞后应约为 1 次装载 + N 次快速渲染)。
        self._grid_lock_guard = threading.Lock()
        self._grid_locks: dict[str, threading.Lock] = {}
        # 在 __init__ 构建(不在模块作用域):PROJ 数据缺失不得影响应用导入。
        self._to_geographic = {
            projection: Transformer.from_crs(projection, "EPSG:4326", always_xy=True)
            for projection in SUPPORTED_PROJECTIONS
        }
        self._from_geographic = {
            projection: Transformer.from_crs("EPSG:4326", projection, always_xy=True)
            for projection in SUPPORTED_PROJECTIONS
        }
        self._source_to_geographic = Transformer.from_crs(SOURCE_CRS, "EPSG:4326", always_xy=True)
        self._geographic_to_source = Transformer.from_crs("EPSG:4326", SOURCE_CRS, always_xy=True)

    # ── 公共 API ────────────────────────────────────────────────────────

    @property
    def dates(self) -> list[str]:
        return sorted(self._files)

    def info(self) -> dict[str, Any]:
        """扫描全部日期,给出字段并集与可用日期;目录为空时优雅返回。"""
        self._refresh_files()
        dates = self.dates
        if not dates:
            return {"dates": [], "fields": [], "default_date": None}
        # 后台预热默认日期网格(不阻塞响应;单飞保证重复触发零成本)
        threading.Thread(target=self.warm_default_grid, name="ice-warm", daemon=True).start()
        field_info: dict[str, dict[str, Any]] = {}
        extent: list[float] | None = None
        for day in dates:
            meta = self._inspect(day)
            if extent is None and meta["extent"]:
                extent = meta["extent"]
            for field, value in meta["fields"].items():
                field_info.setdefault(field, {**value, "available_dates": []})[
                    "available_dates"
                ].append(day)
        return {
            "dates": dates,
            "fields": [{"id": key, **value} for key, value in field_info.items()],
            "default_date": dates[0],
            "source": "netcdf",
            "source_crs": SOURCE_CRS,
            "extent": extent,
            "missing_dates_are_excluded": True,
        }

    def tile(self, field: str, projection: str, day: str, z: int, tx: int, ty: int) -> bytes:
        """渲染单张 256×256 RGBA PNG 瓦片(带 LRU 缓存;渲染在锁外)。"""
        self._validate_tile_request(field, projection, day, z, tx, ty)
        key = (field, projection, day, z, tx, ty)
        with self._lock:
            cached = self._tiles.pop(key, None)
            if cached is not None:
                self._tiles[key] = cached  # LRU:命中重插到尾部
                return cached
        png = self._render(field, projection, day, z, tx, ty)
        with self._lock:
            existing = self._tiles.get(key)
            if existing is not None:
                return existing
            self._tiles[key] = png
            while len(self._tiles) > self._tile_cache_entries:
                self._tiles.pop(next(iter(self._tiles)))
        return png

    def value_at(
        self,
        day: str,
        map_x: float,
        map_y: float,
        projection: str = "EPSG:3413",
        field: str = "concentration",
    ) -> dict[str, Any] | None:
        """返回地图坐标处的**原始网格值**(绝不从 PNG 颜色反推)。

        任何不可用情形(未知日期/无变量/非法坐标/范围外/3857 极点钳制/NoData)
        一律返回 None(路由层按参考实现契约返回 200 {"value": null})。
        0 是有效值,判定一律用 ``is None``,绝不用真值判断。
        """
        if projection not in SUPPORTED_PROJECTIONS or field not in FIELD_ALIASES:
            return None
        if day not in self._files or not np.isfinite(map_x) or not np.isfinite(map_y):
            return None
        if field not in self._inspect(day)["fields"]:
            return None
        try:
            grid = self._grid(day, field)
        except AppError:
            return None
        lon, lat = self._to_geographic[projection].transform(map_x, map_y)
        if not np.isfinite(lon) or not np.isfinite(lat):
            return None
        if projection == "EPSG:3857" and abs(lat) > MERCATOR_MAX_LAT:
            return None
        sx, sy = self._geographic_to_source.transform(lon, lat)
        if not np.isfinite(sx) or not np.isfinite(sy):
            return None
        x, y = grid.x, grid.y
        if sx < x[0] or sx > x[-1] or sy < y[0] or sy > y[-1]:
            return None
        col = int(np.clip(np.searchsorted(x, sx), 1, len(x) - 1))
        if abs(x[col - 1] - sx) <= abs(x[col] - sx):
            col -= 1
        row = int(np.clip(np.searchsorted(y, sy), 1, len(y) - 1))
        if abs(y[row - 1] - sy) <= abs(y[row] - sy):
            row -= 1
        raw = float(grid.values[row, col])
        if not np.isfinite(raw):
            return None
        return {
            "date": day,
            "field": field,
            "value": raw,
            "units": FIELD_UNITS[field],
            "longitude": round(float(lon), 6),
            "latitude": round(float(lat), 6),
            "source_x": round(float(x[col]), 3),
            "source_y": round(float(y[row]), 3),
        }

    def alignment_geojson(self, day: str, projection: str) -> dict[str, Any]:
        """坐标对齐调试:从有效像元采样 5 个控制点(显示投影坐标)。"""
        if projection not in SUPPORTED_PROJECTIONS:
            raise AppError(ICE_PROJECTION_INVALID, "不支持的投影", 404)
        if day not in self._files:
            raise AppError(ICE_DATE_NOT_FOUND, "冰情日期不存在", 404)
        meta = self._inspect(day)
        if "concentration" not in meta["fields"]:
            return {"type": "FeatureCollection", "features": []}
        grid = self._grid(day, "concentration")
        valid = np.isfinite(grid.values)
        rows, cols = grid.values.shape
        features: list[dict[str, Any]] = []
        ratios = ((0.15, 0.20), (0.32, 0.72), (0.50, 0.50), (0.70, 0.28), (0.84, 0.78))
        for index, (row_ratio, col_ratio) in enumerate(ratios, start=1):
            row = int((rows - 1) * row_ratio)
            col = int((cols - 1) * col_ratio)
            found: tuple[int, int] | None = None
            for radius in (80, 240, 600):
                r0, r1 = max(0, row - radius), min(rows, row + radius + 1)
                c0, c1 = max(0, col - radius), min(cols, col + radius + 1)
                candidates = np.argwhere(valid[r0:r1, c0:c1])
                if len(candidates):
                    distances = (candidates[:, 0] + r0 - row) ** 2 + (candidates[:, 1] + c0 - col) ** 2
                    chosen = candidates[int(np.argmin(distances))]
                    found = (int(chosen[0] + r0), int(chosen[1] + c0))
                    break
            if found is None:
                continue
            r, c = found
            lon, lat = self._source_to_geographic.transform(float(grid.x[c]), float(grid.y[r]))
            if projection == "EPSG:3857" and abs(lat) > MERCATOR_MAX_LAT:
                continue
            px, py = self._from_geographic[projection].transform(lon, lat)
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "label": f"控制点 {index}",
                        "raw_value": int(round(float(grid.values[r, c]))),
                        "longitude": round(float(lon), 5),
                        "latitude": round(float(lat), 5),
                    },
                    "geometry": {"type": "Point", "coordinates": [float(px), float(py)]},
                }
            )
        return {
            "type": "FeatureCollection",
            "features": features,
            "crs": {"type": "name", "properties": {"name": projection}},
        }

    # ── 文件索引 ────────────────────────────────────────────────────────

    def _index_files(self) -> dict[str, _FileEntry]:
        files: dict[str, _FileEntry] = {}
        try:
            candidates = sorted(self.root.glob("*.nc"))
        except OSError:  # 目录不存在/不可读 -> 空索引(降级)
            return files
        for path in candidates:
            match = DATE_RE.search(path.name)
            if not match:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            files[match.group(1)] = _FileEntry(path, stat.st_mtime, stat.st_size)
        return files

    def _refresh_files(self) -> None:
        """重扫目录;(mtime,size) 变化的日期逐日期失效 metadata/grid/tile 缓存。"""
        fresh = self._index_files()
        with self._lock:
            changed = {
                day
                for day in set(self._files) | set(fresh)
                if day not in self._files
                or day not in fresh
                or (fresh[day].mtime, fresh[day].size) != (self._files[day].mtime, self._files[day].size)
            }
            for day in changed:
                self._metadata.pop(day, None)
                self._grids.pop(day, None)
                for key in [k for k in self._tiles if k[2] == day]:
                    self._tiles.pop(key, None)
            self._files = fresh  # 原子换绑,读者不会看到半更新索引

    # ── 元数据与网格加载(锁内) ─────────────────────────────────────────

    def _inspect(self, day: str) -> dict[str, Any]:
        cached = self._metadata.get(day)
        if cached is not None:
            return cached
        entry = self._files.get(day)
        meta: dict[str, Any] = {
            "fields": {},
            "x": None,
            "y": None,
            "extent": None,
            "source_crs": SOURCE_CRS,
        }
        if entry is not None:
            try:
                with self._lock, Dataset(str(entry.path)) as dataset:
                    variables = dataset.variables
                    xname = next((n for n in ("x", "lon", "longitude") if n in variables), None)
                    yname = next((n for n in ("y", "lat", "latitude") if n in variables), None)
                    fields: dict[str, dict[str, Any]] = {}
                    for field, aliases in FIELD_ALIASES.items():
                        name = next((n for n in aliases if n in variables), None)
                        if name is None:
                            continue
                        fields[field] = {
                            "name": name,
                            "label": FIELD_LABELS[field],
                            "units": FIELD_UNITS[field],
                            "available": True,
                        }
                    extent = None
                    if xname and yname:
                        x = np.asarray(variables[xname][:], dtype=np.float64)
                        y = np.asarray(variables[yname][:], dtype=np.float64)
                        extent = [
                            float(np.nanmin(x)),
                            float(np.nanmin(y)),
                            float(np.nanmax(x)),
                            float(np.nanmax(y)),
                        ]
                    meta = {
                        "fields": fields,
                        "x": xname,
                        "y": yname,
                        "extent": extent,
                        "source_crs": SOURCE_CRS,
                    }
            except Exception as exc:  # noqa: BLE001 - 损坏文件必须降级而非拖垮服务
                logger.warning("冰情文件不可读,已跳过: %s (%s)", entry.path.name, exc)
        self._metadata[day] = meta
        return meta

    @staticmethod
    def _load_variable(dataset: Dataset, name: str) -> np.ndarray:
        """读取变量为 float64 数组(调用方持锁),掩码与哨兵一律置 NaN。

        参考实现的 ``np.ma.filled(np.asarray(raw), np.nan)`` 在 ``np.asarray``
        处先丢掉了掩码 —— 这里显式取 ``getmaskarray`` 后再填充,并对
        ``_FillValue``/``missing_value`` 哨兵逐值置 NaN。
        """
        variable = dataset.variables[name]
        raw = variable[:]
        mask = np.ma.getmaskarray(raw) if np.ma.isMaskedArray(raw) else None
        data = np.ma.getdata(raw).astype(np.float64)
        if mask is not None and mask.any():
            data[mask] = np.nan
        for attribute in ("_FillValue", "missing_value"):
            if hasattr(variable, attribute):
                for sentinel in np.atleast_1d(
                    np.asarray(getattr(variable, attribute), dtype=np.float64)
                ):
                    if np.isfinite(sentinel):
                        data[data == sentinel] = np.nan
        while data.ndim > 2:
            data = data[0]
        return data

    def _grid(self, day: str, field: str) -> _Grid:
        """按日期+字段加载网格(单飞;归一化在全局锁外;缓存 2 个日期 LRU)。

        关键:缓存检查 → 落盘之间存在归一化窗口,若不设 per-date 装载锁,
        并发首请求会**各自完整装载**网格(数千倍冗余 CPU/内存)。单飞后,
        同一日期的等待者复用第一个线程的结果。
        """
        # 快路径:命中缓存(锁内 O(1))
        with self._lock:
            day_grids = self._grids.get(day)
            if day_grids is not None and field in day_grids:
                self._grids.pop(day)
                self._grids[day] = day_grids  # LRU:命中重插
                return day_grids[field]
        # 单飞:同一日期只有一个线程进入装载区,其余在此等待
        with self._grid_lock_guard:
            load_lock = self._grid_locks.setdefault(day, threading.Lock())
        with load_lock:
            # 双检:等锁期间可能已被其他线程装载完成
            with self._lock:
                day_grids = self._grids.get(day)
                if day_grids is not None and field in day_grids:
                    self._grids.pop(day)
                    self._grids[day] = day_grids
                    return day_grids[field]
                entry = self._files.get(day)
                meta = self._inspect(day)
                field_meta = meta["fields"].get(field)
                if entry is None or field_meta is None or not meta["x"] or not meta["y"]:
                    raise AppError(ICE_FIELD_UNAVAILABLE, "该日期文件没有此变量", 404)
                with Dataset(str(entry.path)) as dataset:
                    x = np.asarray(dataset.variables[meta["x"]][:], dtype=np.float64)
                    y = np.asarray(dataset.variables[meta["y"]][:], dtype=np.float64)
                    raw = self._load_variable(dataset, field_meta["name"])
                    units = str(
                        getattr(dataset.variables[field_meta["name"]], "units", "") or ""
                    ).lower()
            grid = self._normalize(field, raw, units, x, y)  # 全局锁外(仅持该日期装载锁)
            with self._lock:
                grids = self._grids.get(day) or {}
                grids[field] = grid
                self._grids.pop(day, None)
                self._grids[day] = grids  # 日期级 LRU
                while len(self._grids) > 2:
                    self._grids.pop(next(iter(self._grids)))
                return grid

    def warm_default_grid(self) -> None:
        """预载默认日期(最早日期)的密集度网格。

        由 info() 在后台线程调用:用户点开"海冰密集度"时网格已就绪,
        瓦片直接进入 ~50-120ms 的稳定渲染路径(单飞保证幂等,重复调用零成本)。
        """
        dates = self.dates
        if not dates:
            return
        if "concentration" not in self._inspect(dates[0])["fields"]:
            return
        try:
            self._grid(dates[0], "concentration")
        except AppError:
            logger.warning("冰情默认日期网格预热失败: %s", dates[0])

    def _normalize(
        self, field: str, raw: np.ndarray, units: str, x: np.ndarray, y: np.ndarray
    ) -> _Grid:
        """唯一归一化入口:hover 与瓦片共用,数值不可能漂移。"""
        values = raw.astype(np.float32)
        if field == "concentration":
            # 有效域固定 0..100(0 是有效值);127/101/255/负值/NaN 全部 NoData。
            # 不做单位猜测(任务书 §9):域本身就是产品语义。
            invalid = ~np.isfinite(values) | (values < 0) | (values > 100)
            values = np.where(invalid, np.float32("nan"), values).astype(np.float32)
            palette_scale = 0.01
        else:
            factor = 1.0
            if units in ("cm", "centimeter", "centimeters"):
                factor = 0.01
            elif units in ("mm", "millimeter", "millimeters"):
                factor = 0.001
            elif units not in ("", "m", "meter", "meters"):
                if units not in self._warned_units:
                    self._warned_units.add(units)
                    logger.warning("冰情厚度单位未知(units=%r),按原值处理不做换算", units)
            if factor != 1.0:
                values = values * np.float32(factor)
            invalid = ~np.isfinite(values) | (values < 0)
            values = np.where(invalid, np.float32("nan"), values).astype(np.float32)
            palette_scale = 1.0
        if x[0] > x[-1]:
            x = x[::-1].copy()
            values = values[:, ::-1].copy()
        if y[0] > y[-1]:
            y = y[::-1].copy()
            values = values[::-1, :].copy()
        return _Grid(x=x, y=y, values=values, palette_scale=palette_scale)

    # ── 瓦片渲染(锁外 numpy/PIL) ───────────────────────────────────────

    def _validate_tile_request(
        self, field: str, projection: str, day: str, z: int, tx: int, ty: int
    ) -> None:
        if field not in FIELD_ALIASES:
            raise AppError(ICE_FIELD_INVALID, "不支持的冰情字段", 404)
        if projection not in SUPPORTED_PROJECTIONS:
            raise AppError(ICE_PROJECTION_INVALID, "不支持的投影", 404)
        if day not in self._files:
            raise AppError(ICE_DATE_NOT_FOUND, "冰情日期不存在", 404)
        if z < 0 or z > self._max_zoom:
            raise AppError(ICE_TILE_COORD_INVALID, "无效瓦片坐标", 404)
        count = 1 << z
        if tx < 0 or ty < 0 or tx >= count or ty >= count:
            raise AppError(ICE_TILE_COORD_INVALID, "无效瓦片坐标", 404)
        if field not in self._inspect(day)["fields"]:
            raise AppError(ICE_FIELD_UNAVAILABLE, "该日期文件没有此变量", 404)

    def _render(self, field: str, projection: str, day: str, z: int, tx: int, ty: int) -> bytes:
        grid = self._grid(day, field)
        return self._png(grid, projection, z, tx, ty, field)

    def _png(
        self, grid: _Grid, projection: str, z: int, tx: int, ty: int, field: str
    ) -> bytes:
        """瓦片像素中心 → 当前投影 → WGS84 → EPSG:3411 → 最近邻取值 → 调色板插值。

        最近邻(与 hover 查找同口径);3857 超出 ±85.05112878° 保持透明,
        不把极点错误拉伸到瓦片顶部;0 与 NoData 的 alpha 均为 0。
        """
        half = _grid_half(projection)
        width = 2.0 * half / (1 << z)
        offsets = (np.arange(TILE_SIZE) + 0.5) / TILE_SIZE
        gx, gy = np.meshgrid(
            -half + tx * width + offsets * width,
            half - ty * width - offsets * width,
        )
        lon, lat = self._to_geographic[projection].transform(gx, gy)
        in_projection = np.isfinite(lon) & np.isfinite(lat)
        if projection == "EPSG:3857":
            in_projection &= np.abs(lat) <= MERCATOR_MAX_LAT
        sx, sy = self._geographic_to_source.transform(lon, lat)
        x, y, data = grid.x, grid.y, grid.values
        cols = np.interp(sx, x, np.arange(len(x)), left=np.nan, right=np.nan)
        rows = np.interp(sy, y, np.arange(len(y)), left=np.nan, right=np.nan)
        valid = in_projection & np.isfinite(rows) & np.isfinite(cols)
        ri = np.clip(np.rint(np.nan_to_num(rows)).astype(int), 0, data.shape[0] - 1)
        ci = np.clip(np.rint(np.nan_to_num(cols)).astype(int), 0, data.shape[1] - 1)
        values = np.full((TILE_SIZE, TILE_SIZE), np.nan, np.float64)
        values[valid] = data[ri[valid], ci[valid]]

        stops, colors = PALETTE_STOPS[field]
        stops_array = np.asarray(stops, dtype=np.float64)
        colors_array = np.asarray(colors, dtype=np.float64)
        scaled = values * grid.palette_scale
        scaled = np.clip(scaled, 0.0, 1.0 if field == "concentration" else 5.0)
        image = np.zeros((TILE_SIZE, TILE_SIZE, 4), np.uint8)
        mask = np.isfinite(scaled) & (scaled > 0)
        for channel in range(4):
            image[..., channel][mask] = np.interp(
                scaled[mask], stops_array, colors_array[:, channel]
            ).astype(np.uint8)
        output = BytesIO()
        Image.fromarray(image, "RGBA").save(output, "PNG", optimize=True)
        return output.getvalue()
