from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import get_settings
from app.core.database import get_db
from app.models import AuditLog, User
from app.schemas import AuditLogRead, Paginated
from app.services.gwc_backfill import ensure_gwc_3413_backfill

health_router = APIRouter(prefix="/health", tags=["health"])
audit_router = APIRouter(prefix="/admin/audit-logs", tags=["admin-audit"])
admin_router = APIRouter(prefix="/admin/gwc", tags=["admin-gwc"])
settings = get_settings()


@health_router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    probe = settings.storage_root / ".write-probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)
    return {"status": "ready", "database": "ok", "storage": "ok"}


@admin_router.post("/backfill")
def run_gwc_3413_backfill(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Idempotently backfill EPSG:3413 GWC caching for all available S-57 layers."""
    return ensure_gwc_3413_backfill(db)


@audit_router.get("", response_model=Paginated[AuditLogRead])
def list_audit_logs(
    page: int = 1,
    page_size: int = 15,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Paginated[AuditLogRead]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    total = db.scalar(select(func.count()).select_from(AuditLog)) or 0
    items = db.scalars(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Paginated(items=list(items), page=page, page_size=page_size, total=total)

