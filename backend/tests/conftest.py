import os
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["APP_SECRET_KEY"] = "test-secret-key-with-sufficient-length"
os.environ["AUTO_CREATE_SCHEMA"] = "false"
os.environ["COOKIE_SECURE"] = "false"
os.environ["STORAGE_ROOT"] = str(Path(".pytest-storage").resolve())
os.environ["TEMP_ROOT"] = str(Path(".pytest-storage/temp").resolve())
os.environ["INITIAL_ADMIN_USERNAME"] = ""
os.environ["INITIAL_ADMIN_PASSWORD"] = ""
os.environ["GWC_3413_BACKFILL"] = "0"

from app.core.database import Base, get_db
from app.core.security import hash_password
from app.main import app
from app.models import Role, User

test_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


def override_get_db() -> Generator[Session, None, None]:
    with TestSession() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def reset_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    with TestSession() as db:
        db.add_all(
            [
                User(
                    username="admin",
                    display_name="系统管理员",
                    password_hash=hash_password("AdminPass123!"),
                    role=Role.SYSTEM_ADMIN.value,
                ),
                User(
                    username="viewer",
                    display_name="普通用户",
                    password_hash=hash_password("ViewerPass123!"),
                    role=Role.USER.value,
                ),
            ]
        )
        db.commit()
    yield


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def login_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    return login_headers(client, "admin", "AdminPass123!")


@pytest.fixture
def user_headers(client: TestClient) -> dict[str, str]:
    return login_headers(client, "viewer", "ViewerPass123!")


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    with TestSession() as session:
        yield session
