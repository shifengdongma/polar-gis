"""Deterministic synthetic-research environment formulas.

These values are used only for ``allow_synthetic_research`` and are always
marked ``quality=synthetic``.  They are shared by the planner gap-fill and the
environment preview so the UI can show the same values the planner will use.
"""

from __future__ import annotations

from math import atan2, cos, degrees, pi, radians, sin


def phase_radians(latitude: float, longitude: float, day_of_year: int) -> float:
    return radians(latitude * 2.7 + longitude * 0.83 + day_of_year * 3.1)


def synthetic_depth(latitude: float, longitude: float) -> float:
    p = radians(latitude * 1.9 + longitude * 0.55)
    q = radians(latitude * 0.43 - longitude * 1.15)
    continental = sin(p) + 0.55 * sin(q) + 0.2 * cos(0.43 * p)
    if continental > 1.0:
        return 0.0
    return 1800.0 + 1800.0 * (0.5 + 0.5 * sin(p + q))


def synthetic_ice(latitude: float, longitude: float, day_of_year: int) -> tuple[float, float]:
    seasonal = 0.5 + 0.5 * cos(radians(day_of_year - 35))
    polar = min(1.0, max(0.0, (abs(latitude) - 52.0) / 35.0))
    wave = 0.5 + 0.5 * sin(radians(longitude * 2.0 + latitude * 3.0))
    concentration = min(1.0, max(0.0, polar * (0.18 + 0.65 * seasonal) * (0.65 + 0.35 * wave)))
    thickness = min(2.2, max(0.0, concentration * (0.25 + 1.25 * seasonal)))
    return concentration, thickness


def synthetic_wind(
    latitude: float, longitude: float, day_of_year: int
) -> tuple[float, float, float, float]:
    phase = phase_radians(latitude, longitude, day_of_year)
    speed = min(22.0, max(0.5, 6.0 + 5.0 * sin(phase) + 2.5 * cos(0.61 * phase)))
    direction = (180.0 + (1.7 * phase * 180.0 / pi)) % 360.0
    radians_direction = radians(direction)
    u = -speed * sin(radians_direction)
    v = -speed * cos(radians_direction)
    return speed, direction, u, v


def synthetic_current(
    latitude: float, longitude: float, day_of_year: int
) -> tuple[float, float, float, float]:
    phase = phase_radians(latitude, longitude, day_of_year)
    u = 0.35 * sin(phase)
    v = 0.35 * cos(phase)
    speed = (u * u + v * v) ** 0.5
    direction_to = (degrees(atan2(u, v)) + 360.0) % 360.0
    return u, v, speed, direction_to


def synthetic_wave(
    latitude: float, longitude: float, day_of_year: int
) -> tuple[float, float, float]:
    phase = phase_radians(latitude, longitude, day_of_year)
    height = min(
        7.5,
        max(0.1, 1.4 + 1.8 * (0.5 + 0.5 * sin(1.31 * phase)) + 0.7 * abs(sin(0.47 * phase))),
    )
    period = min(14.0, max(3.0, 6.0 + 2.5 * cos(phase)))
    direction = ((2.0 * phase * 180.0 / pi) + 180.0) % 360.0
    return height, period, direction
