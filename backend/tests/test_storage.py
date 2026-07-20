import stat
import zipfile
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.services.storage import LocalStorage


def test_reject_zip_path_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "unsafe")
    settings = Settings(storage_root=tmp_path / "storage", temp_root=tmp_path / "temp")
    storage = LocalStorage(settings)
    with pytest.raises(AppError) as error:
        storage.validate_archive(archive_path)
    assert error.value.code == "UPLOAD_ARCHIVE_UNSAFE"


def test_reject_zip_symbolic_link(tmp_path: Path) -> None:
    archive_path = tmp_path / "symlink.zip"
    link = zipfile.ZipInfo("linked.000")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(link, "target.000")
    settings = Settings(storage_root=tmp_path / "storage", temp_root=tmp_path / "temp")
    storage = LocalStorage(settings)

    with pytest.raises(AppError) as error:
        storage.validate_archive(archive_path)

    assert error.value.code == "UPLOAD_ARCHIVE_UNSAFE"
