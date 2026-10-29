"""Static vessel profiles and depth safety."""

from .depth_safety import DepthSafetyResult, DepthStatus, evaluate_depth
from .models import VesselProfile, VesselSource
from .service import VesselService

__all__ = [
    "DepthSafetyResult",
    "DepthStatus",
    "VesselProfile",
    "VesselService",
    "VesselSource",
    "evaluate_depth",
]
