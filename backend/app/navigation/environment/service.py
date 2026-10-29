"""Fault-isolated environment service over the five field providers."""

from __future__ import annotations

import logging
from datetime import datetime
from math import ceil, cos, radians, sqrt
from pathlib import Path

from app.core.config import Settings
from app.navigation.contracts import (
    DataQuality,
    TimeMatchInfo,
    combine_quality,
    ensure_utc,
)
from app.navigation.environment.manifest import (
    EnvironmentManifest,
    ManifestError,
    load_manifest,
)
from app.navigation.environment.models import (
    EnvironmentSample,
    EnvironmentSnapshot,
    EnvironmentSourceInfo,
    FieldObservation,
    FieldSnapshotInfo,
    ProviderSample,
    VectorObservation,
)
from app.navigation.environment.providers.base import BaseEnvironmentProvider
from app.navigation.environment.synthetic import (
    synthetic_current,
    synthetic_depth,
    synthetic_ice,
    synthetic_wave,
    synthetic_wind,
)

logger = logging.getLogger(__name__)

FIELDS = ("bathymetry", "ice", "wind", "current", "wave")
VECTOR_FIELDS = ("wind", "current", "wave")


class EnvironmentService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = Path(settings.navigation_data_root)
        self._manifest_error: str | None = None
        try:
            self.manifest = load_manifest(settings.resolved_navigation_manifest_path)
        except ManifestError as error:
            self.manifest = EnvironmentManifest()
            self._manifest_error = str(error)
            logger.warning("Navigation manifest invalid: %s", error)

        from app.navigation.environment.providers.carra2 import CARRA2WindProvider
        from app.navigation.environment.providers.gebco import GEBCOBathymetryProvider
        from app.navigation.environment.providers.ice import IceProvider
        from app.navigation.environment.providers.topaz5 import TOPAZ5CurrentProvider
        from app.navigation.environment.providers.wam import WAMWaveProvider

        self._providers: dict[str, BaseEnvironmentProvider] = {
            "bathymetry": GEBCOBathymetryProvider(
                self.root,
                self.manifest,
                tile_cache_entries=settings.navigation_tile_cache_entries,
                max_zoom=settings.navigation_tile_max_zoom,
            ),
            "ice": IceProvider(
                settings.resolved_navigation_ice_data_root,
                settings.ice_data_root,
                self.manifest,
                backend=settings.navigation_ice_backend,
                # Match /api/v1/ice so both paths share the same IceService.
                tile_cache_entries=settings.ice_tile_cache_entries,
                max_zoom=settings.ice_tile_max_zoom,
            ),
            "wind": CARRA2WindProvider(self.root, self.manifest),
            "current": TOPAZ5CurrentProvider(self.root, self.manifest),
            "wave": WAMWaveProvider(self.root, self.manifest),
        }

    # ── source metadata ────────────────────────────────────────────────

    def sources(self) -> list[EnvironmentSourceInfo]:
        result: list[EnvironmentSourceInfo] = []
        for field in FIELDS:
            provider = self._providers[field]
            quality = self.manifest.quality(field)
            available = provider.available() and self._manifest_error is None
            reason = self._manifest_error if self._manifest_error else None
            if not available and reason is None:
                reason = "data_missing"
            result.append(
                EnvironmentSourceInfo(
                    field=field,  # type: ignore[arg-type]
                    available=available,
                    source=provider.source_name,
                    units=_provider_units(field),
                    coverage=provider.coverage(),
                    times=provider.times()[:200],
                    quality=quality if available else DataQuality.MISSING,
                    reason=reason,
                )
            )
        return result

    def times(self, field: str) -> list[datetime]:
        self._validate_field(field)
        return self._providers[field].times()

    # ── point / batch queries ─────────────────────────────────────────

    def query(
        self,
        longitude: float,
        latitude: float,
        requested_time: datetime,
        fields: list[str],
        policy: str,
    ) -> EnvironmentSample:
        requested = ensure_utc(requested_time)
        selected = self._validate_fields(fields)
        self._validate_policy(policy)
        observations = {
            field: self._observe(field, longitude, latitude, requested, policy)
            for field in selected
        }
        qualities = [
            observation.quality
            for observation in observations.values()
            if observation.available
        ]
        summary = combine_quality(qualities) if qualities else DataQuality.MISSING
        return EnvironmentSample(
            longitude=longitude,
            latitude=latitude,
            requested_time=requested,
            data_policy=policy,  # type: ignore[arg-type]
            fields=observations,
            quality_summary=summary,
        )

    def batch_query(
        self,
        points: list[tuple[float, float]],
        requested_time: datetime,
        fields: list[str],
        policy: str,
    ) -> list[EnvironmentSample]:
        if len(points) > self.settings.navigation_max_batch_points:
            raise ValueError(
                f"Batch query supports at most {self.settings.navigation_max_batch_points} points."
            )
        return [
            self.query(longitude, latitude, requested_time, fields, policy)
            for longitude, latitude in points
        ]

    def sample_many(
        self,
        field: str,
        points: list[tuple[float, float]],
        requested_time: datetime,
        policy: str,
    ) -> list[FieldObservation]:
        self._validate_field(field)
        self._validate_policy(policy)
        requested = ensure_utc(requested_time)
        provider = self._providers[field]
        samples = provider.sample_many(
            points,
            requested,
            max_lag_hours=self._max_lag(field),
            allow_future=self._allow_future(policy),
        )
        return [
            self._wrap(field, sample, policy)
            for sample in samples
        ]

    # ── vector fields for map overlays ────────────────────────────────

    def field_vectors(
        self,
        field: str,
        bbox: tuple[float, float, float, float],
        requested_time: datetime,
        *,
        zoom: int,
        max_points: int,
        policy: str,
    ) -> tuple[bool, str | None, list[datetime], list[VectorObservation]]:
        if field not in VECTOR_FIELDS:
            raise ValueError(f"Field vectors are only available for {', '.join(VECTOR_FIELDS)}.")
        self._validate_policy(policy)
        requested = ensure_utc(requested_time)
        provider = self._providers[field]
        if self._manifest_error is not None:
            return False, self._manifest_error, [], []
        if not provider.available() and policy != "allow_synthetic_research":
            return False, "data_missing", [], []
        points = _sample_grid(bbox, zoom, max_points)
        if not points:
            return False, "empty_bbox", [], []
        samples = (
            provider.sample_many(
                points,
                requested,
                max_lag_hours=self._max_lag(field),
                allow_future=self._allow_future(policy),
            )
            if provider.available()
            else None
        )
        observations: list[VectorObservation] = []
        times: list[datetime] = []
        for index, (longitude, latitude) in enumerate(points):
            sample = samples[index] if samples is not None else None
            if sample is None:
                observation = _missing_observation(
                    field, requested, provider.source_name, "data_missing"
                )
            else:
                observation = self._wrap(field, sample, policy)
            if policy == "allow_synthetic_research":
                observation = self._fill_synthetic(
                    field, longitude, latitude, requested, observation
                )
            if observation.time.matched_time is not None:
                times.append(observation.time.matched_time)
            observations.append(
                VectorObservation(
                    id=f"{field}-{index}",
                    longitude=longitude,
                    latitude=latitude,
                    field=field,  # type: ignore[arg-type]
                    available=observation.available,
                    values=observation.values,
                    units=observation.units,
                    quality=observation.quality,
                    source=observation.source,
                    matched_time=observation.time.matched_time,
                    reason=observation.reason,
                )
            )
        if not observations:
            return False, "no_points", [], []
        return (
            any(observation.available for observation in observations),
            None,
            sorted(set(times)),
            observations,
        )

    # ── snapshot for planning ─────────────────────────────────────────

    def snapshot(self, requested_time: datetime, policy: str) -> EnvironmentSnapshot:
        requested = ensure_utc(requested_time)
        self._validate_policy(policy)
        fields: dict[str, FieldSnapshotInfo] = {}
        for field in FIELDS:
            provider = self._providers[field]
            quality = self.manifest.quality(field)
            available = provider.available() and self._manifest_error is None
            if not available:
                fields[field] = FieldSnapshotInfo(
                    field=field,  # type: ignore[arg-type]
                    available=False,
                    source=provider.source_name,
                    quality=DataQuality.MISSING,
                    reason=self._manifest_error or "data_missing",
                )
                continue
            if field == "bathymetry":
                fields[field] = FieldSnapshotInfo(
                    field=field,  # type: ignore[arg-type]
                    available=True,
                    source=provider.source_name,
                    quality=quality,
                    units=_provider_units(field),
                )
                continue
            # Probe at a neutral point only to obtain the provider's time match;
            # point values are intentionally ignored here.
            try:
                probe = provider.sample(
                    0.0,
                    0.0,
                    requested,
                    max_lag_hours=self._max_lag(field),
                    allow_future=self._allow_future(policy),
                )
            except Exception:  # noqa: BLE001
                probe = ProviderSample(
                    available=False,
                    source=provider.source_name,
                    time=TimeMatchInfo(requested_time=requested),
                    reason="time_probe_failed",
                )
            if probe.time.matched_time is None:
                fields[field] = FieldSnapshotInfo(
                    field=field,  # type: ignore[arg-type]
                    available=False,
                    source=provider.source_name,
                    quality=quality,
                    reason=probe.reason or "time_unavailable",
                )
                continue
            fields[field] = FieldSnapshotInfo(
                field=field,  # type: ignore[arg-type]
                available=True,
                source=provider.source_name,
                quality=quality,
                units=_provider_units(field),
                matched_time=probe.time.matched_time,
                valid_time=probe.time.valid_time,
                issue_time=probe.time.issue_time,
            )
        qualities = [
            info.quality for info in fields.values() if info.available
        ]
        return EnvironmentSnapshot(
            requested_time=requested,
            data_policy=policy,  # type: ignore[arg-type]
            quality_summary=combine_quality(qualities) if qualities else DataQuality.MISSING,
            fields=fields,
        )

    # ── tiles ─────────────────────────────────────────────────────────

    def tile(self, field: str, crs: str, z: int, x: int, y: int) -> bytes:
        if field != "bathymetry":
            raise ValueError("Only bathymetry tiles are served by the navigation environment API.")
        provider = self._providers["bathymetry"]
        if not hasattr(provider, "tile"):
            raise ValueError("Bathymetry provider does not support tiles.")
        return provider.tile(crs, z, x, y)  # type: ignore[attr-defined]

    def close(self) -> None:
        for provider in self._providers.values():
            provider.close()

    # ── internals ─────────────────────────────────────────────────────

    def _observe(
        self,
        field: str,
        longitude: float,
        latitude: float,
        requested: datetime,
        policy: str,
    ) -> FieldObservation:
        provider = self._providers[field]
        if self._manifest_error is not None:
            return _missing_observation(
                field,
                requested,
                provider.source_name,
                self._manifest_error,
            )
        if not provider.available():
            missing = _missing_observation(field, requested, provider.source_name, "data_missing")
            return (
                self._fill_synthetic(field, longitude, latitude, requested, missing)
                if policy == "allow_synthetic_research"
                else missing
            )
        try:
            sample = provider.sample(
                longitude,
                latitude,
                requested,
                max_lag_hours=self._max_lag(field),
                allow_future=self._allow_future(policy),
            )
        except Exception as error:  # noqa: BLE001 - one provider must not hide others
            logger.warning("Environment provider %s failed: %s", field, error)
            return _missing_observation(
                field,
                requested,
                provider.source_name,
                f"provider_error:{type(error).__name__}",
            )
        observation = self._wrap(field, sample, policy)
        if policy == "allow_synthetic_research":
            observation = self._fill_synthetic(field, longitude, latitude, requested, observation)
        return observation

    def _fill_synthetic(
        self,
        field: str,
        longitude: float,
        latitude: float,
        requested: datetime,
        observation: FieldObservation,
    ) -> FieldObservation:
        """Fill missing research values with the same deterministic formulas as the planner.

        The result is always labelled synthetic; it is never presented as
        provider-observed data.
        """
        if self._manifest_error is not None:
            return observation
        values = dict(observation.values)
        component_quality = dict(observation.component_quality)
        units = dict(observation.units)
        day = requested.timetuple().tm_yday
        synthetic_values: dict[str, float | bool | None]
        if field == "bathymetry":
            depth = synthetic_depth(latitude, longitude)
            synthetic_values = {"depthM": depth, "isLand": depth <= 0.0}
            units.update({"depthM": "m"})
        elif field == "ice":
            concentration, thickness = synthetic_ice(latitude, longitude, day)
            synthetic_values = {"concentration": concentration, "thicknessM": thickness}
            units.update({"concentration": "1", "thicknessM": "m"})
        elif field == "wind":
            speed, direction, u, v = synthetic_wind(latitude, longitude, day)
            synthetic_values = {
                "speedMs": speed,
                "directionFromDeg": direction,
                "uMs": u,
                "vMs": v,
            }
            units.update({"speedMs": "m/s", "directionFromDeg": "degree", "uMs": "m/s", "vMs": "m/s"})
        elif field == "current":
            u, v, speed, direction = synthetic_current(latitude, longitude, day)
            synthetic_values = {
                "uMs": u,
                "vMs": v,
                "speedMs": speed,
                "directionToDeg": direction,
            }
            units.update({"uMs": "m/s", "vMs": "m/s", "speedMs": "m/s", "directionToDeg": "degree"})
        elif field == "wave":
            height, period, direction = synthetic_wave(latitude, longitude, day)
            synthetic_values = {
                "heightM": height,
                "periodS": period,
                "directionFromDeg": direction,
            }
            units.update({"heightM": "m", "periodS": "s", "directionFromDeg": "degree"})
        else:
            return observation

        filled = False
        for key, value in synthetic_values.items():
            if values.get(key) is None:
                values[key] = value
                component_quality[key] = DataQuality.SYNTHETIC
                filled = True
        if not filled:
            return observation
        source = (
            f"{observation.source}+synthetic-gap-fill-v1"
            if observation.source
            else "synthetic-gap-fill-v1"
        )
        return FieldObservation(
            field=observation.field,
            available=True,
            values=values,
            units=units,
            component_quality=component_quality,
            quality=DataQuality.SYNTHETIC,
            source=source,
            time=(
                observation.time
                if observation.time.matched_time is not None
                else TimeMatchInfo(
                    requested_time=requested,
                    matched_time=requested,
                    valid_time=requested,
                    quality="unknown",
                    match_policy="latest_not_after",
                )
            ),
            reason="synthetic_gap_fill",
            coverage=observation.coverage,
        )

    def _wrap(self, field: str, sample: ProviderSample, policy: str) -> FieldObservation:
        manifest_quality = self.manifest.quality(field)
        quality = manifest_quality if sample.available else DataQuality.MISSING
        reason = sample.reason
        if sample.available and quality is DataQuality.SYNTHETIC and policy == "real_only":
            return _missing_observation(
                field,
                sample.time.requested_time,
                sample.source,
                "synthetic_data_not_allowed",
                sample.time,
            )
        component_quality = {
            key: (manifest_quality if sample.available else DataQuality.MISSING)
            for key in sample.values
        }
        component_quality.update(sample.component_quality)
        return FieldObservation(
            field=field,  # type: ignore[arg-type]
            available=sample.available,
            values=sample.values,
            units=sample.units,
            component_quality=component_quality,
            quality=quality,
            source=sample.source,
            time=sample.time,
            reason=reason,
            coverage=sample.coverage,
        )

    def _max_lag(self, field: str) -> float | None:
        return {
            "bathymetry": None,
            "ice": self.settings.navigation_max_lag_ice_hours,
            "wind": self.settings.navigation_max_lag_wind_hours,
            "current": self.settings.navigation_max_lag_current_hours,
            "wave": self.settings.navigation_max_lag_wave_hours,
        }[field]

    def _allow_future(self, policy: str) -> bool:
        return bool(self.settings.navigation_allow_future_match) or policy == "allow_synthetic_research"

    @staticmethod
    def _validate_policy(policy: str) -> None:
        if policy not in {"real_only", "allow_synthetic_research"}:
            raise ValueError(f"Unsupported data policy: {policy}")

    @staticmethod
    def _validate_field(field: str) -> None:
        if field not in FIELDS:
            raise ValueError(f"Unsupported environment field: {field}")

    def _validate_fields(self, fields: list[str]) -> list[str]:
        if not fields:
            raise ValueError("At least one environment field is required.")
        if len(set(fields)) != len(fields):
            raise ValueError("Environment fields must not repeat.")
        for field in fields:
            self._validate_field(field)
        return fields


def _missing_observation(
    field: str,
    requested_time: datetime,
    source: str | None,
    reason: str,
    time: TimeMatchInfo | None = None,
) -> FieldObservation:
    return FieldObservation(
        field=field,  # type: ignore[arg-type]
        available=False,
        units=_provider_units(field),
        quality=DataQuality.MISSING,
        source=source,
        time=time or TimeMatchInfo(requested_time=requested_time),
        reason=reason,
    )


def _provider_units(field: str) -> dict[str, str]:
    return {
        "bathymetry": {"depthM": "m", "isLand": "bool"},
        "ice": {"concentration": "1", "thicknessM": "m"},
        "wind": {"speedMs": "m/s", "directionFromDeg": "degree", "uMs": "m/s", "vMs": "m/s"},
        "current": {"uMs": "m/s", "vMs": "m/s", "speedMs": "m/s", "directionToDeg": "degree"},
        "wave": {"heightM": "m", "periodS": "s", "directionFromDeg": "degree"},
    }[field]


def _sample_grid(
    bbox: tuple[float, float, float, float],
    zoom: int,
    max_points: int,
) -> list[tuple[float, float]]:
    min_lon, min_lat, max_lon, max_lat = bbox
    if max_lat <= min_lat:
        return []
    width_factor = max(
        1.0,
        abs(max_lon - min_lon)
        * max(0.1, abs(cos(radians((min_lat + max_lat) / 2)))),
    )
    height_factor = max(1.0, max_lat - min_lat)
    aspect = max(1.0, width_factor / height_factor)
    columns = max(2, int(ceil(sqrt(max_points * aspect))))
    rows = max(2, int(ceil(max_points / columns)))
    while columns * rows > max_points and (columns > 2 or rows > 2):
        if columns >= rows and columns > 2:
            columns -= 1
        elif rows > 2:
            rows -= 1
        else:
            break
    lon_span = max_lon - min_lon if max_lon >= min_lon else (max_lon + 360.0) - min_lon
    lats = [min_lat + (index + 0.5) * (max_lat - min_lat) / rows for index in range(rows)]
    lons = [
        _wrap_degrees(min_lon + (index + 0.5) * lon_span / columns)
        for index in range(columns)
    ]
    return [(lon, lat) for lat in lats for lon in lons]


def _wrap_degrees(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0
