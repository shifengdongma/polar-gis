from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID
from xml.etree import ElementTree

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models import FileAsset, Style, Upload, User
from app.schemas import StyleCreate, StyleRead
from app.services.geoserver import GeoServerClient
from app.services.storage import LocalStorage

router = APIRouter(prefix="/admin/styles", tags=["admin-styles"])
settings = get_settings()
storage = LocalStorage(settings)
geoserver = GeoServerClient(settings)


@router.get("", response_model=list[StyleRead])
def list_styles(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[Style]:
    return list(db.scalars(select(Style).where(Style.deleted_at.is_(None))).all())


@router.post("", response_model=StyleRead, status_code=201)
def create_style(
    payload: StyleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Style:
    if db.scalar(select(Style).where(Style.code == payload.code)):
        raise AppError("STYLE_CODE_EXISTS", "样式代码已存在", 409)
    upload = db.get(Upload, payload.upload_id)
    if upload is None or upload.consumed_at is not None:
        raise AppError("UPLOAD_NOT_AVAILABLE", "上传不存在或已被使用", 409)
    if Path(upload.original_name).suffix.lower() != ".sld":
        raise AppError("STYLE_FORMAT_INVALID", "样式文件必须为SLD", 422)
    path = storage.resolve(upload.storage_key)
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as exc:
        raise AppError("STYLE_FORMAT_INVALID", "SLD XML无法解析", 422) from exc
    if not root.tag.endswith("StyledLayerDescriptor"):
        raise AppError("STYLE_FORMAT_INVALID", "文件不是有效SLD", 422)
    geoserver.publish_style(payload.code, path.read_text(encoding="utf-8"))
    asset = FileAsset(
        purpose="style",
        original_name=upload.original_name,
        storage_key=upload.storage_key,
        size_bytes=upload.size_bytes,
        sha256=upload.sha256,
        media_type=upload.media_type,
    )
    db.add(asset)
    db.flush()
    style = Style(
        code=payload.code,
        name=payload.name,
        geoserver_style_name=payload.code,
        file_asset_id=asset.id,
        status="published",
    )
    db.add(style)
    upload.consumed_at = datetime.now(UTC)
    db.commit()
    db.refresh(style)
    return style


@router.delete("/{style_id}", status_code=204)
def delete_style(
    style_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    style = db.get(Style, style_id)
    if style is None or style.deleted_at is not None:
        raise AppError("STYLE_NOT_FOUND", "样式不存在", 404)
    style.deleted_at = datetime.now(UTC)
    db.commit()
