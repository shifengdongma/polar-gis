import hashlib
import os
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from fastapi import UploadFile

from app.core.config import Settings
from app.core.errors import AppError

allowed_suffixes = {
    ".000",
    ".001",
    ".002",
    ".003",
    ".json",
    ".geojson",
    ".tif",
    ".tiff",
    ".zip",
    ".sld",
}


class LocalStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.storage_root.resolve()
        self.temp_root = settings.temp_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)

    def resolve(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        if not candidate.is_relative_to(self.root):
            raise AppError("STORAGE_PATH_INVALID", "存储路径无效", 400)
        return candidate

    def delete(self, storage_key: str) -> bool:
        path = self.resolve(storage_key)
        if not path.exists():
            return False
        path.unlink()
        return True

    async def save_upload(self, upload: UploadFile, user_id: UUID) -> tuple[str, int, str]:
        original_name = Path(upload.filename or "upload.bin").name
        suffix = Path(original_name).suffix.lower()
        if suffix not in allowed_suffixes and not (suffix[1:].isdigit() and len(suffix) == 4):
            raise AppError("UPLOAD_UNSUPPORTED_FORMAT", "不支持的文件格式", 415)
        upload_id = uuid4()
        temp_dir = self.temp_root / str(upload_id)
        temp_dir.mkdir(parents=True, exist_ok=False)
        temp_path = temp_dir / f"source{suffix}"
        digest = hashlib.sha256()
        size = 0
        try:
            with temp_path.open("wb") as target:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.settings.max_upload_bytes:
                        raise AppError("UPLOAD_TOO_LARGE", "上传文件超过5GB限制", 413)
                    digest.update(chunk)
                    target.write(chunk)
            if suffix == ".zip":
                self.validate_archive(temp_path)
            storage_key = f"uploads/{user_id}/{upload_id}/source{suffix}"
            destination = self.resolve(storage_key)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp_path, destination)
            return storage_key, size, digest.hexdigest()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def validate_archive(self, path: Path) -> None:
        try:
            with zipfile.ZipFile(path) as archive:
                total_size = 0
                shapefile_parts: set[str] = set()
                if len(archive.infolist()) > 10000:
                    raise AppError("UPLOAD_ARCHIVE_UNSAFE", "压缩包文件数量过多", 422)
                for member in archive.infolist():
                    pure_path = PurePosixPath(member.filename.replace("\\", "/"))
                    if pure_path.is_absolute() or ".." in pure_path.parts:
                        raise AppError("UPLOAD_ARCHIVE_UNSAFE", "压缩包包含不安全路径", 422)
                    member_type = (member.external_attr >> 16) & 0o170000
                    if member_type == stat.S_IFLNK:
                        raise AppError("UPLOAD_ARCHIVE_UNSAFE", "压缩包包含符号链接", 422)
                    if member.flag_bits & 0x1:
                        raise AppError("UPLOAD_ARCHIVE_UNSAFE", "压缩包包含加密文件", 422)
                    total_size += member.file_size
                    if total_size > self.settings.max_upload_bytes * 4:
                        raise AppError("UPLOAD_ARCHIVE_UNSAFE", "压缩包解压后体积过大", 422)
                    suffix = Path(member.filename).suffix.lower()
                    if suffix in {".shp", ".shx", ".dbf"}:
                        shapefile_parts.add(suffix)
                if shapefile_parts and not {".shp", ".shx", ".dbf"}.issubset(shapefile_parts):
                    raise AppError("UPLOAD_ARCHIVE_INVALID", "Shapefile压缩包缺少必要文件", 422)
        except zipfile.BadZipFile as exc:
            raise AppError("UPLOAD_ARCHIVE_INVALID", "压缩包无法读取", 422) from exc
