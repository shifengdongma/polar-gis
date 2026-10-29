"""Provider interface shared by all environment sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.navigation.environment.models import ProviderSample


class ProviderUnavailable(RuntimeError):
    """Raised when a provider cannot serve a request; callers turn it into a reason."""


class BaseEnvironmentProvider(ABC):
    """One field source with point/batch sampling and explicit time semantics."""

    field: str
    source_name: str

    @abstractmethod
    def available(self) -> bool:
        """Whether any usable data file/index is present."""

    @abstractmethod
    def times(self) -> list[datetime]:
        """Available UTC data times, ascending. May be empty for static fields."""

    @abstractmethod
    def sample(
        self,
        longitude: float,
        latitude: float,
        requested_time: datetime,
        *,
        max_lag_hours: float | None,
        allow_future: bool,
    ) -> ProviderSample:
        """Sample one WGS84 point."""

    def sample_many(
        self,
        points: list[tuple[float, float]],
        requested_time: datetime,
        *,
        max_lag_hours: float | None,
        allow_future: bool,
    ) -> list[ProviderSample]:
        return [
            self.sample(
                longitude,
                latitude,
                requested_time,
                max_lag_hours=max_lag_hours,
                allow_future=allow_future,
            )
            for longitude, latitude in points
        ]

    def coverage(self) -> dict[str, float] | None:
        return None

    @abstractmethod
    def close(self) -> None:
        """Release file handles if the provider keeps them open."""
