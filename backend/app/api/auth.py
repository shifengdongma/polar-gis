from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    refresh_token_expiry,
    verify_password,
)
from app.models import RefreshToken, User
from app.schemas import AccessTokenResponse, LoginRequest, UserRead
from app.services.audit import write_audit

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
refresh_cookie_name = "polar_gis_refresh"


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        refresh_cookie_name,
        token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=f"{settings.api_prefix}/auth",
    )


def issue_session(db: Session, user: User, response: Response) -> AccessTokenResponse:
    access_token, expires_at = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=refresh_token_expiry(),
        )
    )
    set_refresh_cookie(response, refresh_token)
    return AccessTokenResponse(access_token=access_token, expires_at=expires_at)


@router.post("/login", response_model=AccessTokenResponse)
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> AccessTokenResponse:
    user = db.scalar(select(User).where(User.username == payload.username, User.deleted_at.is_(None)))
    now = datetime.now(UTC)
    if user and user.locked_until:
        locked_until = user.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=UTC)
        if locked_until > now:
            raise AppError("AUTH_RATE_LIMITED", "登录失败次数过多，请稍后重试", 429)
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= 5:
                user.locked_until = now + timedelta(minutes=15)
            write_audit(
                db,
                "auth.login",
                "user",
                "failed",
                user=user,
                request_id=request.state.request_id,
            )
            db.commit()
        raise AppError("AUTH_INVALID_CREDENTIALS", "用户名或密码错误", 401)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    token = issue_session(db, user, response)
    write_audit(
        db,
        "auth.login",
        "user",
        "succeeded",
        user=user,
        request_id=request.state.request_id,
    )
    db.commit()
    return token


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh(
    response: Response,
    polar_gis_refresh: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> AccessTokenResponse:
    if not polar_gis_refresh:
        raise AppError("AUTH_INVALID_REFRESH_TOKEN", "刷新令牌无效", 401)
    token_hash = hash_refresh_token(polar_gis_refresh)
    stored = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    now = datetime.now(UTC)
    if stored is None or stored.revoked_at is not None:
        raise AppError("AUTH_INVALID_REFRESH_TOKEN", "刷新令牌无效", 401)
    expires_at = stored.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now or not stored.user.is_active:
        raise AppError("AUTH_INVALID_REFRESH_TOKEN", "刷新令牌无效", 401)
    stored.revoked_at = now
    token = issue_session(db, stored.user, response)
    db.commit()
    return token


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    polar_gis_refresh: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> None:
    if polar_gis_refresh:
        stored = db.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(polar_gis_refresh)
            )
        )
        if stored and stored.revoked_at is None:
            stored.revoked_at = datetime.now(UTC)
            db.commit()
    response.delete_cookie(refresh_cookie_name, path=f"{settings.api_prefix}/auth")


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user

