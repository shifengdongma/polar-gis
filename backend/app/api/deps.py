from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.models import Role, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{get_settings().api_prefix}/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise AppError("AUTH_INVALID_TOKEN", "登录状态无效或已过期", 401) from exc
    user = db.scalar(
        select(User).where(User.id == user_id, User.deleted_at.is_(None), User.is_active.is_(True))
    )
    if user is None:
        raise AppError("AUTH_ACCOUNT_DISABLED", "用户不存在或已停用", 401)
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != Role.SYSTEM_ADMIN.value:
        raise AppError("FORBIDDEN", "当前用户无权执行此操作", 403)
    return current_user

