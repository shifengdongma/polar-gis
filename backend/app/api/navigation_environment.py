"""Navigation environment API: sources, point/batch/vector queries, bathy tiles."""

from __future__ import annotations

import threading
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import User
from app.navigation.environment.models import EnvironmentSample, FieldObservation
from app.navigation.environment.service import EnvironmentService
from app.navigation.schemas import (
    BatchQueryItem,
    BatchQueryRequest,
    BatchQueryResponse,
    EnvironmentQueryRequest,
    EnvironmentSampleRead,
    EnvironmentSourceRead,
    FieldObservationRead,
    FieldQueryRequest,
    FieldQueryResponse,
    TimeMatchRead,
    VectorObservationRead,
)

router = APIRouter(prefix="/navigation/environment", tags=["navigation-environment"])
settings = get_settings()

_service: EnvironmentService | None = None
_service_lock = threading.Lock()


def get_environment_service() -> EnvironmentService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = EnvironmentService(settings)
    return _service


def ensure_navigation_enabled() -> None:
    if not settings.navigation_enabled:
        raise AppError("NAVIGATION_DISABLED", "导航功能未启用", 404)


def _policy(value: str | None) -> str:
    return value or settings.navigation_default_data_policy


def _time_read(value) -> TimeMatchRead:
    return TimeMatchRead(
        requested_time=value.requested_time,
        matched_time=value.matched_time,
        valid_time=value.valid_time,
        issue_time=value.issue_time,
        observation_time=value.observation_time,
        ingest_time=value.ingest_time,
        match_policy=value.match_policy,
        delta_seconds=value.delta_seconds,
        quality=value.quality,
    )


def _field_read(value: FieldObservation) -> FieldObservationRead:
    return FieldObservationRead(
        field=value.field,
        available=value.available,
        values=value.values,
        units=value.units,
        component_quality={key: str(quality) for key, quality in value.component_quality.items()},
        quality=str(value.quality),
        source=value.source,
        time=_time_read(value.time),
        reason=value.reason,
        coverage=value.coverage,
    )


def _sample_read(value: EnvironmentSample) -> EnvironmentSampleRead:
    return EnvironmentSampleRead(
        longitude=value.longitude,
        latitude=value.latitude,
        requested_time=value.requested_time,
        data_policy=value.data_policy,
        fields={key: _field_read(field) for key, field in value.fields.items()},
        quality_summary=str(value.quality_summary),
    )


@router.get("/sources", response_model=list[EnvironmentSourceRead])
def environment_sources(
    _user: User = Depends(get_current_user),
) -> list[EnvironmentSourceRead]:
    ensure_navigation_enabled()
    return [
        EnvironmentSourceRead(
            field=source.field,
            available=source.available,
            source=source.source,
            units=source.units,
            coverage=source.coverage,
            times=source.times,
            quality=str(source.quality),
            reason=source.reason,
        )
        for source in get_environment_service().sources()
    ]


@router.get("/times", response_model=list[datetime])
def environment_times(
    field: str = Query(..., pattern=r"^(bathymetry|ice|wind|current|wave)$"),
    _user: User = Depends(get_current_user),
) -> list[datetime]:
    ensure_navigation_enabled()
    try:
        return get_environment_service().times(field)
    except ValueError as error:
        raise AppError("INPUT_INVALID", str(error), 422) from error


@router.post("/query", response_model=EnvironmentSampleRead)
def environment_query(
    payload: EnvironmentQueryRequest,
    _user: User = Depends(get_current_user),
) -> EnvironmentSampleRead:
    ensure_navigation_enabled()
    try:
        sample = get_environment_service().query(
            payload.longitude,
            payload.latitude,
            payload.time,
            payload.fields,
            _policy(payload.data_policy),
        )
    except ValueError as error:
        raise AppError("INPUT_INVALID", str(error), 422) from error
    return _sample_read(sample)


@router.post("/batch-query", response_model=BatchQueryResponse)
def environment_batch_query(
    payload: BatchQueryRequest,
    _user: User = Depends(get_current_user),
) -> BatchQueryResponse:
    ensure_navigation_enabled()
    points = [(point.longitude, point.latitude) for point in payload.points]
    try:
        samples = get_environment_service().batch_query(
            points,
            payload.time,
            payload.fields,
            _policy(payload.data_policy),
        )
    except ValueError as error:
        raise AppError("INPUT_INVALID", str(error), 422) from error
    return BatchQueryResponse(
        results=[
            BatchQueryItem(id=point.id, environment=_sample_read(sample))
            for point, sample in zip(payload.points, samples, strict=True)
        ]
    )


@router.post("/field", response_model=FieldQueryResponse)
def environment_field(
    payload: FieldQueryRequest,
    _user: User = Depends(get_current_user),
) -> FieldQueryResponse:
    ensure_navigation_enabled()
    min_lon, min_lat, max_lon, max_lat = payload.bbox
    if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
        raise AppError("INPUT_INVALID", "bbox 经度必须在 [-180, 180]", 422)
    if not (-90.0 <= min_lat < max_lat <= 90.0):
        raise AppError("INPUT_INVALID", "bbox 纬度顺序或范围不合法", 422)
    max_points = min(payload.max_points, settings.navigation_field_max_points)
    try:
        available, reason, matched_times, points = get_environment_service().field_vectors(
            payload.field,
            (min_lon, min_lat, max_lon, max_lat),
            payload.time,
            zoom=payload.zoom,
            max_points=max_points,
            policy=_policy(payload.data_policy),
        )
    except ValueError as error:
        raise AppError("INPUT_INVALID", str(error), 422) from error
    source = points[0].source if points else None
    return FieldQueryResponse(
        field=payload.field,
        requested_time=payload.time,
        available=available,
        source=source,
        points=[
            VectorObservationRead(
                id=point.id,
                longitude=point.longitude,
                latitude=point.latitude,
                field=point.field,
                available=point.available,
                values=point.values,
                units=point.units,
                quality=str(point.quality),
                source=point.source,
                matched_time=point.matched_time,
                reason=point.reason,
            )
            for point in points
        ],
        matched_times=matched_times,
        reason=reason,
    )


@router.get(
    "/tiles/{field}/{crs}/{z}/{x}/{y}.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def environment_tile(
    field: str,
    crs: str,
    z: int,
    x: int,
    y: int,
) -> Response:
    """Public scalar-raster tile, mirroring the existing ice tile access boundary."""
    ensure_navigation_enabled()
    if crs not in {"EPSG:3413", "EPSG:3857"}:
        raise AppError("INPUT_INVALID", "不支持的投影", 404)
    if field != "bathymetry":
        raise AppError("INPUT_INVALID", "该字段不提供瓦片", 404)
    try:
        png = get_environment_service().tile(field, crs, z, x, y)
    except ValueError as error:
        raise AppError("TILE_NOT_FOUND", str(error), 404) from error
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )
