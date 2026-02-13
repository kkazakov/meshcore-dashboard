"""
Tests for GET /api/telemetry endpoint.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

import app.api.routes.auth as auth_module
from app.main import app

client = TestClient(app)

# ── Fixtures ──────────────────────────────────────────────────────────────────

_VALID_TOKEN = "test-token-abc123"

_SAMPLE_STATUS = {
    "bat": 3900,
    "uptime": 90061,
    "noise_floor": -95,
    "last_rssi": -80,
    "last_snr": 7.5,
    "tx_queue_len": 0,
    "full_evts": 0,
    "nb_sent": 100,
    "sent_flood": 60,
    "sent_direct": 40,
    "nb_recv": 200,
    "recv_flood": 120,
    "recv_direct": 80,
    "direct_dups": 1,
    "flood_dups": 2,
    "airtime": 5000,
    "rx_airtime": 3000,
    "pubkey_pre": "aabbcc001122",
}

_CONTACT = {
    "id": "contact-1",
    "name": "Repeater-Alpha",
    "data": {"adv_name": "Repeater-Alpha", "public_key": "aabbcc001122"},
}


def _install_token():
    """Insert a known token into the in-memory store."""
    auth_module._token_store[_VALID_TOKEN] = "test@example.com"


def _remove_token():
    auth_module._token_store.pop(_VALID_TOKEN, None)


# ── Auth guard tests ──────────────────────────────────────────────────────────


def test_telemetry_missing_token_returns_401():
    """Requests without x-api-token header are rejected with 401."""
    response = client.get("/api/telemetry?repeater_name=Alpha")
    assert response.status_code == 401


def test_telemetry_invalid_token_returns_401():
    """Requests with an unknown token are rejected with 401."""
    response = client.get(
        "/api/telemetry?repeater_name=Alpha",
        headers={"x-api-token": "not-a-real-token"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["detail"]["status"] == "unauthorized"


# ── Parameter validation ──────────────────────────────────────────────────────


def test_telemetry_no_params_returns_400():
    """Requests with neither repeater_name nor public_key return 400."""
    _install_token()
    try:
        response = client.get(
            "/api/telemetry",
            headers={"x-api-token": _VALID_TOKEN},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["detail"]["status"] == "error"
    finally:
        _remove_token()


# ── Happy path ────────────────────────────────────────────────────────────────


def test_telemetry_by_name_success():
    """Returns 200 with wrapped telemetry data when contact found by name."""
    _install_token()
    try:
        with (
            patch(
                "app.api.routes.telemetry.telemetry_common.connect_to_device",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
            patch(
                "app.api.routes.telemetry.telemetry_common.find_contact_by_name",
                new_callable=AsyncMock,
                return_value=_CONTACT,
            ),
            patch(
                "app.api.routes.telemetry.telemetry_common.get_status",
                new_callable=AsyncMock,
                return_value=_SAMPLE_STATUS,
            ),
        ):
            response = client.get(
                "/api/telemetry?repeater_name=Alpha",
                headers={"x-api-token": _VALID_TOKEN},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        data = body["data"]
        assert data["contact_name"] == "Repeater-Alpha"
        assert data["public_key"] == "aabbcc001122"
        assert data["battery"]["mv"] == 3900
        assert data["battery"]["v"] == 3.9
        assert isinstance(data["battery"]["percentage"], float)
        assert data["uptime"]["days"] == 1
        assert data["radio"]["noise_floor"] == -95
        assert data["packets"]["sent"]["total"] == 100
    finally:
        _remove_token()


def test_telemetry_by_public_key_success():
    """Returns 200 when contact found by public_key (name lookup returns None)."""
    _install_token()
    try:
        with (
            patch(
                "app.api.routes.telemetry.telemetry_common.connect_to_device",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
            patch(
                "app.api.routes.telemetry.telemetry_common.find_contact_by_public_key",
                new_callable=AsyncMock,
                return_value=_CONTACT,
            ),
            patch(
                "app.api.routes.telemetry.telemetry_common.get_status",
                new_callable=AsyncMock,
                return_value=_SAMPLE_STATUS,
            ),
        ):
            response = client.get(
                "/api/telemetry?public_key=aabbcc001122",
                headers={"x-api-token": _VALID_TOKEN},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    finally:
        _remove_token()


# ── Error path ────────────────────────────────────────────────────────────────


def test_telemetry_contact_not_found_returns_404():
    """Returns 404 when the contact cannot be located on the device."""
    _install_token()
    try:
        with (
            patch(
                "app.api.routes.telemetry.telemetry_common.connect_to_device",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
            patch(
                "app.api.routes.telemetry.telemetry_common.find_contact_by_name",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            response = client.get(
                "/api/telemetry?repeater_name=Ghost",
                headers={"x-api-token": _VALID_TOKEN},
            )

        assert response.status_code == 404
        assert response.json()["detail"]["status"] == "error"
    finally:
        _remove_token()


def test_telemetry_device_offline_returns_504():
    """Returns 504 when the device does not respond with telemetry."""
    _install_token()
    try:
        with (
            patch(
                "app.api.routes.telemetry.telemetry_common.connect_to_device",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
            patch(
                "app.api.routes.telemetry.telemetry_common.find_contact_by_name",
                new_callable=AsyncMock,
                return_value=_CONTACT,
            ),
            patch(
                "app.api.routes.telemetry.telemetry_common.get_status",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            response = client.get(
                "/api/telemetry?repeater_name=Alpha",
                headers={"x-api-token": _VALID_TOKEN},
            )

        assert response.status_code == 504
        assert response.json()["detail"]["status"] == "error"
    finally:
        _remove_token()


def test_telemetry_connection_failure_returns_502():
    """Returns 502 when the MeshCore device cannot be reached."""
    _install_token()
    try:
        with patch(
            "app.api.routes.telemetry.telemetry_common.connect_to_device",
            new_callable=AsyncMock,
            side_effect=OSError("connection refused"),
        ):
            response = client.get(
                "/api/telemetry?repeater_name=Alpha",
                headers={"x-api-token": _VALID_TOKEN},
            )

        assert response.status_code == 502
        assert response.json()["detail"]["status"] == "error"
    finally:
        _remove_token()


# ── Telemetry history tests ───────────────────────────────────────────────────

_REPEATER_ID = "550e8400-e29b-41d4-a716-446655440000"


def _make_dt(iso: str):
    from datetime import datetime, timezone

    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


_HISTORY_ROWS = [
    ("battery_voltage", _make_dt("2026-02-13T05:40:59.072"), 3.65),
    ("battery_voltage", _make_dt("2026-02-13T05:50:59.072"), 3.75),
    ("battery_percentage", _make_dt("2026-02-13T05:40:59.072"), 85.0),
]


def test_telemetry_history_missing_token_returns_401():
    """History endpoint rejects requests without a token."""
    response = client.get(f"/api/telemetry/history/{_REPEATER_ID}?keys=battery_voltage")
    assert response.status_code == 401


def test_telemetry_history_missing_keys_returns_400():
    """History endpoint returns 400 when keys param is absent."""
    _install_token()
    try:
        response = client.get(
            f"/api/telemetry/history/{_REPEATER_ID}",
            headers={"x-api-token": _VALID_TOKEN},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["status"] == "error"
    finally:
        _remove_token()


def test_telemetry_history_empty_keys_returns_400():
    """History endpoint returns 400 when keys param is blank."""
    _install_token()
    try:
        response = client.get(
            f"/api/telemetry/history/{_REPEATER_ID}?keys=",
            headers={"x-api-token": _VALID_TOKEN},
        )
        assert response.status_code == 400
    finally:
        _remove_token()


def test_telemetry_history_success():
    """Returns grouped data for each requested key."""
    _install_token()
    try:
        mock_result = MagicMock()
        mock_result.result_rows = _HISTORY_ROWS

        with patch("app.api.routes.telemetry.get_client") as mock_get_client:
            mock_get_client.return_value.query.return_value = mock_result

            response = client.get(
                f"/api/telemetry/history/{_REPEATER_ID}"
                "?keys=battery_voltage,battery_percentage"
                "&from=2026-02-13T00:00:00"
                "&to=2026-02-13T23:59:59",
                headers={"x-api-token": _VALID_TOKEN},
            )

        assert response.status_code == 200
        body = response.json()
        assert "data" in body

        voltage = body["data"]["battery_voltage"]
        assert len(voltage) == 2
        assert voltage[0]["value"] == "3.65"
        assert voltage[1]["value"] == "3.75"
        assert "2026-02-13" in voltage[0]["date"]

        percentage = body["data"]["battery_percentage"]
        assert len(percentage) == 1
        assert percentage[0]["value"] == "85.0"
    finally:
        _remove_token()


def test_telemetry_history_unknown_key_returns_empty_list():
    """Keys with no matching rows are returned as empty lists."""
    _install_token()
    try:
        mock_result = MagicMock()
        mock_result.result_rows = []

        with patch("app.api.routes.telemetry.get_client") as mock_get_client:
            mock_get_client.return_value.query.return_value = mock_result

            response = client.get(
                f"/api/telemetry/history/{_REPEATER_ID}?keys=nonexistent_metric",
                headers={"x-api-token": _VALID_TOKEN},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["nonexistent_metric"] == []
    finally:
        _remove_token()


def test_telemetry_history_omitted_to_defaults_to_now():
    """Omitting the to parameter returns results up to now()."""
    _install_token()
    try:
        mock_result = MagicMock()
        mock_result.result_rows = _HISTORY_ROWS

        with patch("app.api.routes.telemetry.get_client") as mock_get_client:
            mock_get_client.return_value.query.return_value = mock_result

            response = client.get(
                f"/api/telemetry/history/{_REPEATER_ID}"
                "?keys=battery_voltage,battery_percentage"
                "&from=2026-02-13T00:00:00",
                headers={"x-api-token": _VALID_TOKEN},
            )

        assert response.status_code == 200
        # Verify now64() was used — to_dt param must NOT be in the call kwargs
        call_args = mock_get_client.return_value.query.call_args
        assert "to_dt" not in call_args.kwargs.get("parameters", {})
        assert "now64()" in call_args.args[0]
    finally:
        _remove_token()


def test_telemetry_history_space_separated_datetime():
    """Accepts space-separated datetimes (e.g. '2025-02-10 00:00:00')."""
    _install_token()
    try:
        mock_result = MagicMock()
        mock_result.result_rows = []

        with patch("app.api.routes.telemetry.get_client") as mock_get_client:
            mock_get_client.return_value.query.return_value = mock_result

            response = client.get(
                f"/api/telemetry/history/{_REPEATER_ID}"
                "?keys=battery_voltage"
                "&from=2025-02-10 00:00:00"
                "&to=2025-02-14 00:00:00",
                headers={"x-api-token": _VALID_TOKEN},
            )

        assert response.status_code == 200
    finally:
        _remove_token()


def test_telemetry_history_invalid_datetime_returns_400():
    """Returns 400 when from or to cannot be parsed as a datetime."""
    _install_token()
    try:
        response = client.get(
            f"/api/telemetry/history/{_REPEATER_ID}?keys=battery_voltage&from=not-a-date",
            headers={"x-api-token": _VALID_TOKEN},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["status"] == "error"
    finally:
        _remove_token()


def test_telemetry_history_db_error_returns_503():
    """Returns 503 when ClickHouse raises an exception."""
    _install_token()
    try:
        with patch("app.api.routes.telemetry.get_client") as mock_get_client:
            mock_get_client.return_value.query.side_effect = RuntimeError("db down")

            response = client.get(
                f"/api/telemetry/history/{_REPEATER_ID}?keys=battery_voltage",
                headers={"x-api-token": _VALID_TOKEN},
            )

        assert response.status_code == 503
        assert response.json()["detail"]["status"] == "error"
    finally:
        _remove_token()
