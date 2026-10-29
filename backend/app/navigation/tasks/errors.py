"""Typed planning-task errors mapped to API error codes."""


class PlanningTaskError(Exception):
    code = "PLANNER_FAILED"
    status_code = 400

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class PlanningLimitExceeded(PlanningTaskError):
    code = "PLANNER_LIMIT_EXCEEDED"
    status_code = 429


class PlanningNotFound(PlanningTaskError):
    code = "PLAN_NOT_FOUND"
    status_code = 404


class PlanningNotCancellable(PlanningTaskError):
    code = "PLAN_NOT_CANCELLABLE"
    status_code = 409


class PlanningNotEditable(PlanningTaskError):
    code = "PLAN_NOT_EDITABLE"
    status_code = 409
