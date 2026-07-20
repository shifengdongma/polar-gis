from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def write_audit(
    db: Session,
    action: str,
    resource_type: str,
    result: str,
    user: User | None = None,
    resource_id: str | None = None,
    request_id: str | None = None,
    changes: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else None,
        role=user.role if user else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        request_id=request_id,
        changes=changes or {},
    )
    db.add(entry)
    return entry

