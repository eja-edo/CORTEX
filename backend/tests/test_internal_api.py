"""
Tests for Internal API Endpoints

Tests the internal service-to-service communication endpoints.
"""

import pytest
from uuid import uuid4
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import app
from app.models import Asset, AssetStatus
from app.database import get_db


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_internal_api_key():
    """Mock INTERNAL_API_KEY for testing."""
    with patch("app.api.internal.settings.INTERNAL_API_KEY", "test-secret-key-123"):
        yield


@pytest.fixture
def mock_db():
    """Mock database session using app dependency override."""
    mock_session = MagicMock(spec=Session)
    
    # Override the get_db dependency - FastAPI will call next() on the generator
    def override_get_db():
        yield mock_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    yield mock_session
    
    # Clean up override after test
    app.dependency_overrides.clear()


class TestInternalHealthCheck:
    """Test /internal/health endpoint."""

    def test_health_check_with_valid_key(self, client, mock_internal_api_key):
        """Health check should return status with valid API key."""
        response = client.get(
            "/internal/health",
            headers={"X-Internal-API-Key": "test-secret-key-123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "backend"
        assert "ocr_service_mode" in data

    def test_health_check_with_invalid_key(self, client, mock_internal_api_key):
        """Health check should reject invalid API key."""
        response = client.get(
            "/internal/health",
            headers={"X-Internal-API-Key": "wrong-key"},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Invalid internal API key"

    def test_health_check_without_key(self, client):
        """Health check should reject missing API key."""
        response = client.get("/internal/health")
        assert response.status_code == 422  # Validation error for missing header


class TestUpdateAssetStatus:
    """Test /internal/assets/{id}/status endpoint."""

    def test_update_status_to_completed(
        self, client, mock_internal_api_key, mock_db
    ):
        """Should update asset status to completed."""
        asset_id = uuid4()
        mock_asset = MagicMock()
        mock_asset.status = AssetStatus.PROCESSING
        mock_db.query.return_value.filter.return_value.first.return_value = mock_asset

        response = client.patch(
            f"/internal/assets/{asset_id}/status",
            headers={"X-Internal-API-Key": "test-secret-key-123"},
            json={"status": "completed"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["status"] == "completed"
        assert mock_asset.status == AssetStatus.COMPLETED
        mock_db.commit.assert_called_once()

    def test_update_status_to_failed_with_reason(
        self, client, mock_internal_api_key, mock_db
    ):
        """Should update asset status to failed with reason."""
        asset_id = uuid4()
        mock_asset = MagicMock()
        mock_asset.status = AssetStatus.PROCESSING
        mock_db.query.return_value.filter.return_value.first.return_value = mock_asset

        response = client.patch(
            f"/internal/assets/{asset_id}/status",
            headers={"X-Internal-API-Key": "test-secret-key-123"},
            json={
                "status": "failed",
                "failed_reason": "OCR pipeline crashed: CUDA out of memory",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert mock_asset.status == AssetStatus.FAILED
        assert mock_asset.failed_reason == "OCR pipeline crashed: CUDA out of memory"

    def test_update_status_asset_not_found(
        self, client, mock_internal_api_key, mock_db
    ):
        """Should return 404 if asset doesn't exist."""
        asset_id = uuid4()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        response = client.patch(
            f"/internal/assets/{asset_id}/status",
            headers={"X-Internal-API-Key": "test-secret-key-123"},
            json={"status": "completed"},
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_update_status_invalid_status(
        self, client, mock_internal_api_key, mock_db
    ):
        """Should return 400 for invalid status value."""
        asset_id = uuid4()

        response = client.patch(
            f"/internal/assets/{asset_id}/status",
            headers={"X-Internal-API-Key": "test-secret-key-123"},
            json={"status": "invalid_status"},
        )

        assert response.status_code == 400
        assert "Invalid status" in response.json()["detail"]

    def test_update_status_unauthorized(self, client, mock_internal_api_key):
        """Should reject requests with wrong API key."""
        asset_id = uuid4()

        response = client.patch(
            f"/internal/assets/{asset_id}/status",
            headers={"X-Internal-API-Key": "wrong-key"},
            json={"status": "completed"},
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "Invalid internal API key"
