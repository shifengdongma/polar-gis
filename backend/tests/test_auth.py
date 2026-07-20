from fastapi.testclient import TestClient


def test_health_live(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_login_and_current_user(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/auth/me", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["role"] == "system_admin"


def test_invalid_credentials_are_generic(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "incorrect"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_INVALID_CREDENTIALS"


def test_user_cannot_access_admin_api(
    client: TestClient,
    user_headers: dict[str, str],
) -> None:
    response = client.get("/api/v1/admin/users", headers=user_headers)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_admin_can_create_user(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={
            "username": "analyst",
            "displayName": "分析用户",
            "password": "AnalystPass123!",
            "role": "user",
        },
    )
    assert response.status_code == 201
    assert response.json()["username"] == "analyst"


def test_create_user_rejects_short_password(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={
            "username": "demo",
            "displayName": "演示用户",
            "password": "123456",
            "role": "user",
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_last_admin_cannot_be_disabled(client: TestClient, admin_headers: dict[str, str]) -> None:
    users = client.get("/api/v1/admin/users", headers=admin_headers).json()["items"]
    admin = next(item for item in users if item["username"] == "admin")
    response = client.patch(
        f"/api/v1/admin/users/{admin['id']}",
        headers=admin_headers,
        json={"isActive": False},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "LAST_ADMIN_REQUIRED"
