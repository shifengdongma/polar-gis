"""Tests for S-57 basemap API endpoint access control and error handling."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import get_settings


class TestBasemapAccessControl:
    """Verify admin-only access for basemap endpoints."""

    def test_profiles_requires_admin(self, client: TestClient):
        response = client.get("/api/v1/admin/s57-basemaps/profiles")
        assert response.status_code in (401, 403)

    def test_preflight_requires_admin(self, client: TestClient):
        response = client.post(
            "/api/v1/admin/s57-basemaps/preflight",
            json={"profileCode": "global_overview_v1", "sourceType": "server_directory"},
        )
        assert response.status_code in (401, 403)

    def test_import_requires_admin(self, client: TestClient):
        response = client.post(
            "/api/v1/admin/s57-basemaps/import",
            json={
                "profileCode": "global_overview_v1",
                "manifestHash": "a" * 64,
                "sourceType": "server_directory",
            },
        )
        assert response.status_code in (401, 403)

    def test_run_detail_requires_admin(self, client: TestClient):
        response = client.get(
            "/api/v1/admin/s57-basemaps/runs/00000000-0000-0000-0000-000000000000",
        )
        assert response.status_code in (401, 403)


class TestBasemapProfilesAsAdmin:
    def test_list_profiles(self, client: TestClient, admin_headers: dict):
        response = client.get(
            "/api/v1/admin/s57-basemaps/profiles", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestBasemapPreflightAsAdmin:
    def test_preflight_empty_source(
        self, client: TestClient, admin_headers: dict
    ):
        """When source directory is empty/missing, preflight should still succeed
        with canStart=false and appropriate counts."""
        response = client.post(
            "/api/v1/admin/s57-basemaps/preflight",
            json={"profileCode": "global_overview_v1", "sourceType": "server_directory"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        # response uses camelCase via ApiModel alias
        assert data.get("canStart") is False or data.get("can_start") is False
        assert data.get("selectedFileCount", data.get("selected_file_count", 0)) == 0
        assert data.get("expectedCellCount", data.get("expected_cell_count", 0)) == 18


class TestBasemapRunsAsAdmin:
    def test_nonexistent_run_returns_404(
        self, client: TestClient, admin_headers: dict
    ):
        response = client.get(
            "/api/v1/admin/s57-basemaps/runs/00000000-0000-0000-0000-000000000000",
            headers=admin_headers,
        )
        assert response.status_code == 404
