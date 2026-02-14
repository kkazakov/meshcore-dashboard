"""
Tests for GET /status endpoint.
"""

from unittest.mock import MagicMock, patch
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _mock_token_client(valid: bool = True) -> MagicMock:
    """Create a mock ClickHouse client for token validation."""
    mock_result = MagicMock()
    mock_result.result_rows = [["test@example.com"]] if valid else []
    mock_ch = MagicMock()
    mock_ch.query.return_value = mock_result
    return mock_ch


@contextmanager
def _mock_tokens_table(valid: bool = True):
    """Context manager that mocks the tokens table."""
    mock_client = _mock_token_client(valid)
    with patch("app.api.routes.status.get_client", return_value=mock_client):
        yield


def test_status_ok():
    """Returns 200 with status=ok when ClickHouse is reachable."""
    with patch("app.api.routes.status.ping", return_value=(True, 1.23)):
        response = client.get("/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["clickhouse"]["connected"] is True
    assert body["clickhouse"]["latency_ms"] == 1.23
    assert body["authenticated"] is False


def test_status_degraded():
    """Returns 200 with status=degraded when ClickHouse is unreachable."""
    with patch("app.api.routes.status.ping", return_value=(False, 500.0)):
        response = client.get("/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["clickhouse"]["connected"] is False
    assert body["authenticated"] is False


def test_status_authenticated_with_valid_token():
    """Returns authenticated=true when a valid session token is supplied."""
    with (
        patch("app.api.routes.status.ping", return_value=(True, 1.0)),
        _mock_tokens_table(valid=True),
    ):
        response = client.get("/status", headers={"x-api-token": "validtoken123"})

    assert response.status_code == 200
    assert response.json()["authenticated"] is True


def test_status_not_authenticated_with_wrong_token():
    """Returns authenticated=false when the token is not in the store."""
    with (
        patch("app.api.routes.status.ping", return_value=(True, 1.0)),
        _mock_tokens_table(valid=False),
    ):
        response = client.get("/status", headers={"x-api-token": "wrongtoken"})

    assert response.status_code == 200
    assert response.json()["authenticated"] is False


def test_status_not_authenticated_without_token():
    """Returns authenticated=false when no x-api-token header is provided."""
    with patch("app.api.routes.status.ping", return_value=(True, 1.0)):
        response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["authenticated"] is False
