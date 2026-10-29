"""Polar-GIS navigation domain (environment, vessel, risk, planner).

This package is the only home for migrated PolarOptionNav-System-V3 business
logic. It must not import ``core.*`` / ``services.*`` from the reference repo,
and it must not create a second FastAPI application or configuration system.
"""

NAVIGATION_CONTRACT_VERSION = "1.0"

__all__ = ["NAVIGATION_CONTRACT_VERSION"]
