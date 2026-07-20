from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import hash_password
from app.models import Role, User
from app.schemas import Paginated, PasswordReset, UserCreate, UserRead, UserUpdate
from app.services.audit import write_audit

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


@router.get("", response_model=Paginated[UserRead])
def list_users(
    page: int = 1,
    page_size: int = 15,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Paginated[UserRead]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    condition = User.deleted_at.is_(None)
    total = db.scalar(select(func.count()).select_from(User).where(condition)) or 0
    items = db.scalars(
        select(User)
        .where(condition)
        .order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Paginated(items=list(items), page=page, page_size=page_size, total=total)


@router.post("", response_model=UserRead, status_code=201)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    if db.scalar(select(User).where(User.username == payload.username)):
        raise AppError("USER_ALREADY_EXISTS", "用户名已存在", 409)
    user = User(
        username=payload.username,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        role=payload.role.value,
    )
    db.add(user)
    db.flush()
    write_audit(
        db,
        "user.create",
        "user",
        "succeeded",
        user=admin,
        resource_id=str(user.id),
        request_id=request.state.request_id,
        changes={"username": user.username, "role": user.role},
    )
    db.commit()
    db.refresh(user)
    return user


def get_user_or_404(db: Session, user_id: UUID) -> User:
    user = db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    if user is None:
        raise AppError("USER_NOT_FOUND", "用户不存在", 404)
    return user


def ensure_admin_remains(db: Session, target: User, new_role: str | None, new_active: bool | None) -> None:
    loses_admin = target.role == Role.SYSTEM_ADMIN.value and (
        new_role == Role.USER.value or new_active is False
    )
    if not loses_admin:
        return
    admin_count = db.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.role == Role.SYSTEM_ADMIN.value,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    if admin_count == 1:
        raise AppError("LAST_ADMIN_REQUIRED", "系统必须保留至少一个有效管理员", 409)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    user = get_user_or_404(db, user_id)
    ensure_admin_remains(
        db,
        user,
        payload.role.value if payload.role else None,
        payload.is_active,
    )
    changes = payload.model_dump(exclude_unset=True)
    if payload.role is not None:
        changes["role"] = payload.role.value
    for key, value in changes.items():
        setattr(user, key, value)
    write_audit(
        db,
        "user.update",
        "user",
        "succeeded",
        user=admin,
        resource_id=str(user.id),
        request_id=request.state.request_id,
        changes=changes,
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/reset-password", status_code=204)
def reset_password(
    user_id: UUID,
    payload: PasswordReset,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> None:
    user = get_user_or_404(db, user_id)
    user.password_hash = hash_password(payload.password)
    write_audit(
        db,
        "user.reset_password",
        "user",
        "succeeded",
        user=admin,
        resource_id=str(user.id),
        request_id=request.state.request_id,
    )
    db.commit()


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> None:
    user = get_user_or_404(db, user_id)
    ensure_admin_remains(db, user, Role.USER.value, False)
    user.deleted_at = datetime.now(UTC)
    user.is_active = False
    write_audit(
        db,
        "user.delete",
        "user",
        "succeeded",
        user=admin,
        resource_id=str(user.id),
        request_id=request.state.request_id,
    )
    db.commit()

