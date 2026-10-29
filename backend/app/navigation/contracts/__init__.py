"""Explicit navigation contracts: coordinates, time, units, quality, evidence."""

from .coordinates import (
    LocalENUFrameRef,
    LocalENUPosition,
    LocalFrame,
    WGS84Position,
    bearing_to_math_yaw,
    math_yaw_to_bearing,
    wrap_2pi,
    wrap_pi,
)
from .directions import (
    CurrentDirectionTo,
    WaveDirectionFrom,
    WindDirectionFrom,
    from_bearing_speed_to_en,
    from_bearing_to_to_bearing,
    to_bearing_speed_to_en,
)
from .evidence import EvidenceRecord, EvidenceStatus, ParameterEvidence
from .quality import AvailabilityStatus, DataQuality, QualityMetadata, combine_quality
from .status import FeasibilityStatus
from .time import (
    TimeMatchInfo,
    TimeMatchPolicy,
    TimeMatchQuality,
    TimeMetadata,
    available_at_decision_time,
    data_age,
    ensure_utc,
    lead_time,
    staleness,
    within_max_lag,
)
from .units import (
    KNOT_METRES_PER_SECOND,
    NAUTICAL_MILE_METRES,
    degrees_to_radians,
    knots_to_metres_per_second,
    metres_per_second_to_knots,
    metres_to_nautical_miles,
    nautical_miles_to_metres,
    radians_to_degrees,
)

NAVIGATION_CONTRACT_VERSION = "1.0"

__all__ = [
    "AvailabilityStatus",
    "CurrentDirectionTo",
    "DataQuality",
    "EvidenceRecord",
    "EvidenceStatus",
    "FeasibilityStatus",
    "KNOT_METRES_PER_SECOND",
    "LocalENUFrameRef",
    "LocalENUPosition",
    "LocalFrame",
    "NAUTICAL_MILE_METRES",
    "NAVIGATION_CONTRACT_VERSION",
    "ParameterEvidence",
    "QualityMetadata",
    "TimeMatchInfo",
    "TimeMatchPolicy",
    "TimeMatchQuality",
    "TimeMetadata",
    "WGS84Position",
    "WaveDirectionFrom",
    "WindDirectionFrom",
    "available_at_decision_time",
    "bearing_to_math_yaw",
    "combine_quality",
    "data_age",
    "degrees_to_radians",
    "ensure_utc",
    "from_bearing_speed_to_en",
    "from_bearing_to_to_bearing",
    "knots_to_metres_per_second",
    "lead_time",
    "math_yaw_to_bearing",
    "metres_per_second_to_knots",
    "metres_to_nautical_miles",
    "nautical_miles_to_metres",
    "radians_to_degrees",
    "staleness",
    "to_bearing_speed_to_en",
    "within_max_lag",
    "wrap_2pi",
    "wrap_pi",
]
