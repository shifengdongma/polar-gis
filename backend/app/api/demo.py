from datetime import UTC, datetime, timedelta
from math import sin

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import User
from app.schemas import WeatherPointRequest

router = APIRouter(prefix="/demo", tags=["demo"])
settings = get_settings()
disclaimer = "演示数据，仅用于功能验证，不代表实时或权威海洋信息。"


def ensure_demo_enabled() -> None:
    if not settings.demo_data_enabled:
        raise AppError("DEMO_DATA_DISABLED", "演示数据功能未启用", 404)


@router.get("/ais/vessels")
def demo_ais(_: User = Depends(get_current_user)) -> dict:
    ensure_demo_enabled()
    return {
        "isDemo": True,
        "disclaimer": disclaimer,
        "observedAt": datetime.now(UTC).isoformat(),
        "items": [
            {"mmsi": "412000001", "name": "极地探索01", "longitude": 80.2, "latitude": 72.1, "course": 35, "speed": 9.8},
            {"mmsi": "412000002", "name": "海冰调查02", "longitude": 76.8, "latitude": 74.0, "course": 110, "speed": 6.4},
            {"mmsi": "412000003", "name": "北纬保障03", "longitude": 88.4, "latitude": 70.8, "course": 278, "speed": 12.1},
        ],
    }


@router.post("/weather/point")
def demo_weather(
    payload: WeatherPointRequest,
    _: User = Depends(get_current_user),
) -> dict:
    ensure_demo_enabled()
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    points = []
    for hour in range(0, 73, 3):
        points.append(
            {
                "forecastAt": (start + timedelta(hours=hour)).isoformat(),
                "temperatureC": round(-4 + sin(hour / 10) * 3, 1),
                "windSpeedMs": round(5 + sin(hour / 7) * 2, 1),
                "windDirectionDeg": int((230 + hour * 4) % 360),
                "waveHeightM": round(1.2 + sin(hour / 9) * 0.5, 1),
            }
        )
    return {
        "isDemo": True,
        "disclaimer": disclaimer,
        "coordinate": payload.coordinate,
        "crs": payload.crs,
        "generatedAt": datetime.now(UTC).isoformat(),
        "items": points,
    }

