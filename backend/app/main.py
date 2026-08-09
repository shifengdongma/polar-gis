import logging
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api import (
    auth,
    base_maps,
    datasets,
    demo,
    layers,
    projects,
    s57_basemaps,
    styles,
    system,
    users,
)
from app.core.config import get_settings
from app.core.database import SessionLocal, init_database
from app.core.errors import AppError, app_error_handler, validation_error_handler
from app.core.middleware import RequestContextMiddleware
from app.core.security import hash_password
from app.models import Role, User

settings = get_settings()
logger = logging.getLogger(__name__)


def ensure_initial_admin() -> None:
    if not settings.initial_admin_username or not settings.initial_admin_password:
        return
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.username == settings.initial_admin_username))
        if existing:
            return
        db.add(
            User(
                username=settings.initial_admin_username,
                display_name="系统管理员",
                password_hash=hash_password(settings.initial_admin_password),
                role=Role.SYSTEM_ADMIN.value,
                is_active=True,
                created_at=datetime.now(UTC),
            )
        )
        db.commit()


def _spawn_gwc_3413_backfill() -> None:
    """Start the GWC EPSG:3413 backfill in a daemon thread.

    Non-blocking: startup proceeds even if GeoServer is unreachable; failures
    are logged as warnings. Disabled by setting GWC_3413_BACKFILL=0.
    """

    def _run() -> None:
        try:
            from app.core.database import SessionLocal
            from app.services.gwc_backfill import ensure_gwc_3413_backfill

            with SessionLocal() as db:
                result = ensure_gwc_3413_backfill(db)
                logger.info("GWC EPSG:3413 回填完成: %s", result)
        except Exception as exc:
            logger.warning("GWC EPSG:3413 回填失败: %s", exc)

    threading.Thread(target=_run, name="gwc-3413-backfill", daemon=True).start()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    settings.temp_root.mkdir(parents=True, exist_ok=True)
    init_database()
    ensure_initial_admin()
    _spawn_gwc_3413_backfill()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)

api = settings.api_prefix
app.include_router(auth.router, prefix=api)
app.include_router(users.router, prefix=api)
app.include_router(projects.public_router, prefix=api)
app.include_router(projects.admin_router, prefix=api)
app.include_router(datasets.router, prefix=api)
app.include_router(layers.public_router, prefix=api)
app.include_router(layers.admin_router, prefix=api)
app.include_router(base_maps.public_router, prefix=api)
app.include_router(base_maps.admin_router, prefix=api)
app.include_router(styles.router, prefix=api)
app.include_router(demo.router, prefix=api)
app.include_router(s57_basemaps.router, prefix=api)
app.include_router(system.health_router, prefix=api)
app.include_router(system.audit_router, prefix=api)
app.include_router(system.admin_router, prefix=api)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": settings.app_name, "status": "ok", "docs": "/docs"}
