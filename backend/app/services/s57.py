import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.errors import AppError

s57_name_pattern = re.compile(r"^(?P<cell>[A-Za-z0-9_-]+)\.(?P<update>\d{3})$")


@dataclass(frozen=True)
class S57FileIdentity:
    cell_name: str
    update_number: int


def identify_s57_file(path: Path) -> S57FileIdentity:
    match = s57_name_pattern.match(path.name)
    if not match:
        raise AppError("S57_FILENAME_INVALID", "S-57文件名必须包含单元名和三位更新号", 422)
    return S57FileIdentity(
        cell_name=match.group("cell").upper(),
        update_number=int(match.group("update")),
    )


def validate_s57_update(
    candidate: S57FileIdentity,
    expected_cell_name: str,
    current_update_number: int,
) -> None:
    if candidate.cell_name != expected_cell_name.upper():
        raise AppError("S57_CELL_MISMATCH", "更新文件与当前海图单元不匹配", 422)
    expected_update = current_update_number + 1
    if candidate.update_number != expected_update:
        raise AppError(
            "S57_UPDATE_GAP",
            f"期望更新号为{expected_update:03d}，实际为{candidate.update_number:03d}",
            422,
        )


class GdalInspector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def ensure_available(self) -> None:
        if shutil.which(self.settings.gdal_ogrinfo_command) is None:
            raise AppError("GDAL_UNAVAILABLE", "未找到ogrinfo，请安装并配置GDAL", 503)

    def inspect(self, path: Path) -> dict[str, Any]:
        self.ensure_available()
        result = subprocess.run(
            [self.settings.gdal_ogrinfo_command, "-ro", "-so", "-al", "-json", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            raise AppError("GDAL_INSPECTION_FAILED", "GDAL无法读取上传数据", 422, result.stderr[-2000:])
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AppError("GDAL_OUTPUT_INVALID", "GDAL检查结果无法解析", 500) from exc

    def inspect_raster(self, path: Path) -> dict[str, Any]:
        if shutil.which(self.settings.gdal_info_command) is None:
            raise AppError("GDAL_UNAVAILABLE", "未找到gdalinfo，请安装并配置GDAL", 503)
        result = subprocess.run(
            [self.settings.gdal_info_command, "-json", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            raise AppError("GDAL_INSPECTION_FAILED", "GDAL无法读取栅格数据", 422, result.stderr[-2000:])
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AppError("GDAL_OUTPUT_INVALID", "GDAL栅格检查结果无法解析", 500) from exc

    def s57_metadata(self, path: Path) -> dict[str, Any]:
        identity = identify_s57_file(path)
        result = self.inspect(path)
        metadata = result.get("metadata", {}) if isinstance(result, dict) else {}
        return {
            "cellName": identity.cell_name,
            "updateNumber": identity.update_number,
            "driver": result.get("driverShortName", "S57"),
            "layerCount": len(result.get("layers", [])),
            "sourceMetadata": metadata,
        }
