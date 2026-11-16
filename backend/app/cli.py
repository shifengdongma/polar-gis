import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import Role, User


def create_admin(username: str, password: str, display_name: str) -> None:
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == username)):
            raise SystemExit(f"User {username} already exists")
        db.add(
            User(
                username=username,
                display_name=display_name,
                password_hash=hash_password(password),
                role=Role.SYSTEM_ADMIN.value,
            )
        )
        db.commit()


def s57_inventory(root: Path, output: Path | None = None) -> None:
    """Read-only inventory of local S-57 base cells and update chains."""
    settings = get_settings()
    if not root.is_dir():
        raise SystemExit(f"目录不存在：{root}")
    base_files = sorted(
        path
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() == ".000"
    )
    cells: list[dict] = []
    for base in base_files:
        stem = base.stem
        updates = sorted(
            path
            for path in root.iterdir()
            if path.is_file()
            and path.stem == stem
            and path.suffix[1:].isdigit()
            and int(path.suffix[1:]) > 0
        )
        update_numbers = sorted(int(path.suffix[1:]) for path in updates)
        missing_updates = [
            number
            for number in range(1, (max(update_numbers) + 1) if update_numbers else 1)
            if number not in update_numbers
        ]
        cell: dict = {
            "cell": stem,
            "baseFile": base.name,
            "updateFiles": [path.name for path in updates],
            "missingUpdates": [f"{number:03d}" for number in missing_updates],
            "readOk": False,
            "layers": [],
            "error": None,
        }
        try:
            completed = subprocess.run(
                [
                    settings.gdal_ogrinfo_command,
                    "-ro",
                    "-so",
                    "-al",
                    "-json",
                    str(base),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
            if completed.returncode != 0:
                cell["error"] = (
                    completed.stderr.strip()
                    or completed.stdout.strip()
                    or f"ogrinfo exit {completed.returncode}"
                )
            else:
                data = json.loads(completed.stdout)
                cell["readOk"] = True
                for layer in data.get("layers", []):
                    geometry = (layer.get("geometryFields") or [{}])[0]
                    cell["layers"].append(
                        {
                            "name": layer.get("name"),
                            "featureCount": layer.get("featureCount"),
                            "geometryType": geometry.get("type"),
                            "extent": geometry.get("extent"),
                        }
                    )
        except FileNotFoundError:
            raise SystemExit(
                f"未找到 GDAL 命令 {settings.gdal_ogrinfo_command!r}；"
                "请在 backend 容器内运行本命令或安装 GDAL。"
            ) from None
        except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
            cell["error"] = str(exc)
        cells.append(cell)

    document = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "root": str(root),
        "baseCellCount": len(cells),
        "readableCellCount": sum(1 for cell in cells if cell["readOk"]),
        "cellsWithMissingUpdates": [
            cell["cell"] for cell in cells if cell["missingUpdates"]
        ],
        "cells": cells,
    }
    rendered = json.dumps(document, ensure_ascii=False, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"已写入 {output}")
    else:
        print(rendered)


def main() -> None:
    parser = argparse.ArgumentParser(prog="polar-gis")
    commands = parser.add_subparsers(dest="command", required=True)
    admin_parser = commands.add_parser("create-admin")
    admin_parser.add_argument("--username", required=True)
    admin_parser.add_argument("--password", required=True)
    admin_parser.add_argument("--display-name", default="系统管理员")
    inventory_parser = commands.add_parser("s57-inventory")
    inventory_parser.add_argument("--root", required=True)
    inventory_parser.add_argument("--output", default=None)
    args = parser.parse_args()
    if args.command == "create-admin":
        create_admin(args.username, args.password, args.display_name)
    elif args.command == "s57-inventory":
        s57_inventory(Path(args.root), Path(args.output) if args.output else None)


if __name__ == "__main__":
    main()

