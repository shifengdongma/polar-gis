from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import AppError
from app.models import BaseMap, User
from app.schemas import BaseMapCreate, BaseMapRead

public_router = APIRouter(prefix="/base-maps", tags=["base-maps"])
admin_router = APIRouter(prefix="/admin/base-maps", tags=["admin-base-maps"])


@public_router.get("", response_model=list[BaseMapRead])
def list_enabled_base_maps(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[BaseMap]:
    return list(
        db.scalars(
            select(BaseMap).where(
                BaseMap.is_enabled.is_(True),
                BaseMap.deleted_at.is_(None),
            )
        ).all()
    )


@admin_router.get("", response_model=list[BaseMapRead])
def list_base_maps(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[BaseMap]:
    return list(db.scalars(select(BaseMap).where(BaseMap.deleted_at.is_(None))).all())


@admin_router.post("", response_model=BaseMapRead, status_code=201)
def create_base_map(
    payload: BaseMapCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> BaseMap:
    base_map = BaseMap(**payload.model_dump())
    db.add(base_map)
    db.commit()
    db.refresh(base_map)
    return base_map


@admin_router.patch("/{base_map_id}", response_model=BaseMapRead)
def update_base_map(
    base_map_id: UUID,
    payload: BaseMapCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> BaseMap:
    base_map = db.get(BaseMap, base_map_id)
    if base_map is None or base_map.deleted_at is not None:
        raise AppError("BASE_MAP_NOT_FOUND", "底图不存在", 404)
    for key, value in payload.model_dump().items():
        setattr(base_map, key, value)
    db.commit()
    db.refresh(base_map)
    return base_map


@admin_router.delete("/{base_map_id}", status_code=204)
def delete_base_map(
    base_map_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    base_map = db.get(BaseMap, base_map_id)
    if base_map is None or base_map.deleted_at is not None:
        raise AppError("BASE_MAP_NOT_FOUND", "底图不存在", 404)
    base_map.deleted_at = datetime.now(UTC)
    base_map.is_enabled = False
    db.commit()

