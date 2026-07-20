import argparse

from sqlalchemy import select

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


def main() -> None:
    parser = argparse.ArgumentParser(prog="polar-gis")
    commands = parser.add_subparsers(dest="command", required=True)
    admin_parser = commands.add_parser("create-admin")
    admin_parser.add_argument("--username", required=True)
    admin_parser.add_argument("--password", required=True)
    admin_parser.add_argument("--display-name", default="系统管理员")
    args = parser.parse_args()
    if args.command == "create-admin":
        create_admin(args.username, args.password, args.display_name)


if __name__ == "__main__":
    main()

