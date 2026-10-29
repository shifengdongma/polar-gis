"""Planner control-flow exceptions (not environment data)."""


class PlanningCancelled(RuntimeError):
    """The planning run was cancelled by the user."""


class PlanningTimeout(RuntimeError):
    """The planning run exceeded its cooperative deadline."""
