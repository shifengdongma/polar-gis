"""冰情图层 API —— NetCDF 派生的只读 PNG XYZ 瓦片与原始值查询。

鉴权边界(刻意偏离其余 /api/v1 数据端点,理由必须保留):
- 冰情按"与现有地图瓦片相同的只读访问边界"设计 —— OpenLayers XYZ 的原生
  <img> 请求无法携带 Bearer,而生产环境的地图瓦片(/geoserver 经 nginx)
  本就是无鉴权读取;后端只在内网(internal network),外部唯一入口是 web/nginx。
- 因此本路由**不设置任何鉴权依赖**;熔断开关为 ICE_ENABLED。
- 对应的端点契约文档在 docs/09-system-architecture.md 的 Ice Overlay 节。

服务实例经懒工厂 ``get_ice_service()`` 获取(双重检查,不用 lru_cache/Depends):
- 目录缺失 / PROJ 数据异常不得拖垮应用导入(冰情失败 != 地图失败);
- 测试与运维可 monkeypatch 本模块的 ``get_ice_service`` 名称(house 惯例)。
"""

from __future__ import annotations

import threading

from fastapi import APIRouter, Path, Query, Response

from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas import IceInfoRead, IceValueRead
from app.services.ice import IceService

router = APIRouter(prefix="/ice", tags=["ice"])
settings = get_settings()

_service: IceService | None = None
_service_lock = threading.Lock()


def get_ice_service() -> IceService:
    """进程级 IceService(首次使用时构建;设置经 Settings 注入,绝无硬编码路径)。"""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = IceService(
                    settings.ice_data_root,
                    tile_cache_entries=settings.ice_tile_cache_entries,
                    max_zoom=settings.ice_tile_max_zoom,
                )
    return _service


def ensure_ice_enabled() -> None:
    if not settings.ice_enabled:
        raise AppError("ICE_DISABLED", "冰情功能未启用", 404)


@router.get("/info", response_model=IceInfoRead, response_model_exclude_unset=True)
def ice_info() -> dict:
    """扫描数据目录:实际存在的日期、字段并集与各字段可用日期、源网格范围。

    空目录时响应精确为 ``{"dates": [], "fields": [], "defaultDate": null}``
    (降级契约:无数据 `!=` 地图不可用)。
    """
    ensure_ice_enabled()
    return get_ice_service().info()


@router.get("/value", response_model=IceValueRead, response_model_exclude_unset=True)
def ice_value(
    date: str = Query(..., pattern=r"^\d{8}$"),
    x: float = Query(...),
    y: float = Query(...),
    projection: str = Query("EPSG:3413", pattern=r"^EPSG:(3413|3857)$"),
    field: str = Query("concentration"),
) -> IceValueRead:
    """地图坐标处的原始网格值。miss 一律 200 且响应体精确为 {"value": null}。"""
    ensure_ice_enabled()
    value = get_ice_service().value_at(date, x, y, projection, field)
    if value is None:
        return IceValueRead(value=None)
    return IceValueRead(**value)


@router.get("/alignment")
def ice_alignment(
    date: str = Query(..., pattern=r"^\d{8}$"),
    projection: str = Query("EPSG:3413", pattern=r"^EPSG:(3413|3857)$"),
) -> dict:
    """坐标对齐调试控制点(GeoJSON,坐标为请求的显示投影)。未知日期/投影 404。"""
    ensure_ice_enabled()
    return get_ice_service().alignment_geojson(date, projection)


@router.get(
    "/{field}/{projection}/tile/{z}/{x}/{y}.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def ice_tile(
    field: str,
    projection: str,
    z: int = Path(ge=0),
    x: int = Path(ge=0),
    y: int = Path(ge=0),
    date: str = Query(..., pattern=r"^\d{8}$"),
) -> Response:
    """256×256 RGBA PNG 瓦片。z 上限由 ICE_TILE_MAX_ZOOM 在服务内校验(404)。"""
    ensure_ice_enabled()
    png = get_ice_service().tile(field, projection, date, z, x, y)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )
