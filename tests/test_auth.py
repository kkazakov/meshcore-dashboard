"""
Tests for POST /api/login endpoint.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import bcrypt
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_HASH = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()

_ACTIVE_ROW = [(_HASH, "alice", True, "")]
_INACTIVE_ROW = [(_HASH, "alice", False, "")]


def _mock_client(rows: list) -> MagicMock:
    """Return a mock ClickHouse client whose query() yields *rows*."""
    mock_result = MagicMock()
    mock_result.result_rows = rows
    mock_ch = MagicMock()
    mock_ch.query.return_value = mock_result
    return mock_ch


def test_login_success():
    """Returns 200 and user details when credentials are valid."""
    mock_result = MagicMock()
    mock_result.type = MagicMock()
    mock_result.payload = {"name": "test-device"}

    mock_meshcore = MagicMock()
    mock_meshcore.commands.send_appstart = AsyncMock(return_value=mock_result)
    mock_meshcore.disconnect = AsyncMock()

    with (
        patch("app.api.routes.auth.get_client", return_value=_mock_client(_ACTIVE_ROW)),
        patch(
            "app.api.routes.auth.telemetry_common.connect_to_device",
            new_callable=AsyncMock,
            return_value=mock_meshcore,
        ),
    ):
        response = client.post(
            "/api/login", json={"email": "alice@example.com", "password": "secret"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert body["username"] == "alice"
    assert body["access_rights"] == ""
    assert body["device_name"] == "test-device"
    assert isinstance(body["token"], str) and len(body["token"]) == 64


def test_login_success_stores_token_in_memory():
    """Each successful login mints a unique token stored in the module-level dict."""
    import app.api.routes.auth as auth_module

    with patch(
        "app.api.routes.auth.get_client", return_value=_mock_client(_ACTIVE_ROW)
    ):
        r1 = client.post(
            "/api/login", json={"email": "alice@example.com", "password": "secret"}
        )
        r2 = client.post(
            "/api/login", json={"email": "alice@example.com", "password": "secret"}
        )

    t1 = r1.json()["token"]
    t2 = r2.json()["token"]
    assert t1 != t2
    assert t1 in auth_module._token_store
    assert t2 in auth_module._token_store


def test_login_wrong_password():
    """Returns 401 when the password does not match the stored hash."""
    with patch(
        "app.api.routes.auth.get_client", return_value=_mock_client(_ACTIVE_ROW)
    ):
        response = client.post(
            "/api/login", json={"email": "alice@example.com", "password": "wrong"}
        )

    assert response.status_code == 401


def test_login_unknown_user():
    """Returns 401 when no matching user is found."""
    with patch("app.api.routes.auth.get_client", return_value=_mock_client([])):
        response = client.post(
            "/api/login", json={"email": "nobody@example.com", "password": "x"}
        )

    assert response.status_code == 401


def test_login_inactive_account():
    """Returns 401 when the account is not active."""
    with patch(
        "app.api.routes.auth.get_client", return_value=_mock_client(_INACTIVE_ROW)
    ):
        response = client.post(
            "/api/login", json={"email": "alice@example.com", "password": "secret"}
        )

    assert response.status_code == 401
    assert "inactive" in response.json()["detail"].lower()


def test_login_database_unavailable():
    """Returns 503 when ClickHouse raises an exception."""
    mock_ch = MagicMock()
    mock_ch.query.side_effect = Exception("connection refused")
    with patch("app.api.routes.auth.get_client", return_value=mock_ch):
        response = client.post(
            "/api/login", json={"email": "alice@example.com", "password": "secret"}
        )

    assert response.status_code == 503
