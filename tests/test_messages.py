"""
Tests for POST /api/messages endpoint.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

import app.api.routes.auth as auth_module
from app.main import app
from meshcore import EventType

client = TestClient(app)

# ── Fixtures ──────────────────────────────────────────────────────────────────

_VALID_TOKEN = "test-token-messages-xyz"


def _install_token() -> None:
    auth_module._token_store[_VALID_TOKEN] = "test@example.com"


def _remove_token() -> None:
    auth_module._token_store.pop(_VALID_TOKEN, None)


def _make_channel_event(idx: int, name: str) -> MagicMock:
    """Build a fake get_channel() Event with the given slot data."""
    evt = MagicMock()
    evt.type = EventType.OK
    evt.payload = {
        "channel_idx": idx,
        "channel_name": name,
        "channel_secret": bytes([0xAB] * 16),
    }
    return evt


def _make_ok_event() -> MagicMock:
    evt = MagicMock()
    evt.type = EventType.OK
    return evt


def _make_error_event(reason: str = "rejected") -> MagicMock:
    evt = MagicMock()
    evt.type = EventType.ERROR
    evt.payload = reason
    return evt


def _build_meshcore_mock(channels: list[tuple[int, str]]) -> MagicMock:
    """
    Return a MeshCore mock whose get_channel() returns the given channels,
    followed by an ERROR event (end-of-list sentinel).
    """
    meshcore = MagicMock()

    channel_events = [_make_channel_event(idx, name) for idx, name in channels]
    # ERROR terminates the scan loop in _resolve_channel_index
    channel_events.append(_make_error_event())

    meshcore.commands.get_channel = AsyncMock(side_effect=channel_events)
    meshcore.commands.send_chan_msg = AsyncMock(return_value=_make_ok_event())
    meshcore.disconnect = AsyncMock()
    return meshcore


# ── Auth guard tests ──────────────────────────────────────────────────────────


def test_send_message_missing_token_returns_401():
    """Requests without x-api-token are rejected with 401."""
    response = client.post("/api/messages", json={"channel": "#test", "message": "hello"})
    assert response.status_code == 401


def test_send_message_invalid_token_returns_401():
    """Requests with an unknown token are rejected with 401."""
    response = client.post(
        "/api/messages",
        json={"channel": "#test", "message": "hello"},
        headers={"x-api-token": "bad-token"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["status"] == "unauthorized"


# ── Input validation ──────────────────────────────────────────────────────────


def test_send_message_empty_channel_returns_400():
    _install_token()
    try:
        response = client.post(
            "/api/messages",
            json={"channel": "", "message": "hello"},
            headers={"x-api-token": _VALID_TOKEN},
        )
        assert response.status_code == 400
        assert "channel" in response.json()["detail"]["message"]
    finally:
        _remove_token()


def test_send_message_empty_message_returns_400():
    _install_token()
    try:
        response = client.post(
            "/api/messages",
            json={"channel": "#test", "message": ""},
            headers={"x-api-token": _VALID_TOKEN},
        )
        assert response.status_code == 400
        assert "message" in response.json()["detail"]["message"]
    finally:
        _remove_token()


# ── Happy path ────────────────────────────────────────────────────────────────


def test_send_message_success_with_hash_prefix():
    """``#test`` resolves to the 'test' channel and returns 200."""
    _install_token()
    meshcore_mock = _build_meshcore_mock([(0, "test"), (1, "general")])

    with (
        patch(
            "app.api.routes.messages.telemetry_common.load_config",
            return_value={},
        ),
        patch(
            "app.api.routes.messages.telemetry_common.connect_to_device",
            new=AsyncMock(return_value=meshcore_mock),
        ),
    ):
        try:
            response = client.post(
                "/api/messages",
                json={"channel": "#test", "message": "Проба 123"},
                headers={"x-api-token": _VALID_TOKEN},
            )
        finally:
            _remove_token()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["channel_name"] == "test"
    assert body["channel_index"] == 0
    # Verify the library call used the right slot index and the full text.
    meshcore_mock.commands.send_chan_msg.assert_awaited_once_with(0, "Проба 123")


def test_send_message_success_without_hash_prefix():
    """``test`` (no ``#``) also resolves correctly."""
    _install_token()
    meshcore_mock = _build_meshcore_mock([(0, "test")])

    with (
        patch(
            "app.api.routes.messages.telemetry_common.load_config",
            return_value={},
        ),
        patch(
            "app.api.routes.messages.telemetry_common.connect_to_device",
            new=AsyncMock(return_value=meshcore_mock),
        ),
    ):
        try:
            response = client.post(
                "/api/messages",
                json={"channel": "test", "message": "hello"},
                headers={"x-api-token": _VALID_TOKEN},
            )
        finally:
            _remove_token()

    assert response.status_code == 200
    body = response.json()
    assert body["channel_name"] == "test"


def test_send_message_channel_stored_with_hash():
    """Device channel named ``#test`` is found when requesting ``#test``."""
    _install_token()
    meshcore_mock = _build_meshcore_mock([(1, "#test")])

    with (
        patch(
            "app.api.routes.messages.telemetry_common.load_config",
            return_value={},
        ),
        patch(
            "app.api.routes.messages.telemetry_common.connect_to_device",
            new=AsyncMock(return_value=meshcore_mock),
        ),
    ):
        try:
            response = client.post(
                "/api/messages",
                json={"channel": "#test", "message": "Проба 123"},
                headers={"x-api-token": _VALID_TOKEN},
            )
        finally:
            _remove_token()

    assert response.status_code == 200
    body = response.json()
    assert body["channel_name"] == "#test"
    assert body["channel_index"] == 1
    meshcore_mock.commands.send_chan_msg.assert_awaited_once_with(1, "Проба 123")


def test_send_message_channel_name_case_insensitive():
    """Channel matching is case-insensitive: ``#TEST`` finds ``test``."""
    _install_token()
    meshcore_mock = _build_meshcore_mock([(2, "test")])

    with (
        patch(
            "app.api.routes.messages.telemetry_common.load_config",
            return_value={},
        ),
        patch(
            "app.api.routes.messages.telemetry_common.connect_to_device",
            new=AsyncMock(return_value=meshcore_mock),
        ),
    ):
        try:
            response = client.post(
                "/api/messages",
                json={"channel": "#TEST", "message": "hi"},
                headers={"x-api-token": _VALID_TOKEN},
            )
        finally:
            _remove_token()

    assert response.status_code == 200
    assert response.json()["channel_index"] == 2


# ── Error paths ───────────────────────────────────────────────────────────────


def test_send_message_channel_not_found_returns_404():
    """Requesting a channel that does not exist on the device returns 404."""
    _install_token()
    # Device has no channels (immediate ERROR from get_channel).
    meshcore_mock = MagicMock()
    meshcore_mock.commands.get_channel = AsyncMock(return_value=_make_error_event())
    meshcore_mock.disconnect = AsyncMock()

    with (
        patch(
            "app.api.routes.messages.telemetry_common.load_config",
            return_value={},
        ),
        patch(
            "app.api.routes.messages.telemetry_common.connect_to_device",
            new=AsyncMock(return_value=meshcore_mock),
        ),
    ):
        try:
            response = client.post(
                "/api/messages",
                json={"channel": "#ghost", "message": "anyone?"},
                headers={"x-api-token": _VALID_TOKEN},
            )
        finally:
            _remove_token()

    assert response.status_code == 404
    assert "ghost" in response.json()["detail"]["message"]


def test_send_message_device_connection_failure_returns_502():
    """A connection error to the MeshCore device returns 502."""
    _install_token()

    with (
        patch(
            "app.api.routes.messages.telemetry_common.load_config",
            return_value={},
        ),
        patch(
            "app.api.routes.messages.telemetry_common.connect_to_device",
            new=AsyncMock(side_effect=OSError("device not found")),
        ),
    ):
        try:
            response = client.post(
                "/api/messages",
                json={"channel": "#test", "message": "hello"},
                headers={"x-api-token": _VALID_TOKEN},
            )
        finally:
            _remove_token()

    assert response.status_code == 502
    assert "Device connection failed" in response.json()["detail"]["message"]


def test_send_message_device_rejects_send_returns_502():
    """If send_chan_msg returns an ERROR event, the endpoint returns 502."""
    _install_token()
    meshcore_mock = _build_meshcore_mock([(0, "test")])
    meshcore_mock.commands.send_chan_msg = AsyncMock(
        return_value=_make_error_event("firmware error")
    )

    with (
        patch(
            "app.api.routes.messages.telemetry_common.load_config",
            return_value={},
        ),
        patch(
            "app.api.routes.messages.telemetry_common.connect_to_device",
            new=AsyncMock(return_value=meshcore_mock),
        ),
    ):
        try:
            response = client.post(
                "/api/messages",
                json={"channel": "#test", "message": "hello"},
                headers={"x-api-token": _VALID_TOKEN},
            )
        finally:
            _remove_token()

    assert response.status_code == 502
    assert "rejected" in response.json()["detail"]["message"]


def test_send_message_device_send_timeout_returns_504():
    """If send_chan_msg times out, the endpoint returns 504."""
    _install_token()
    meshcore_mock = _build_meshcore_mock([(0, "test")])

    async def _slow(*_args, **_kwargs):
        await asyncio.sleep(999)

    meshcore_mock.commands.send_chan_msg = _slow

    with (
        patch(
            "app.api.routes.messages.telemetry_common.load_config",
            return_value={},
        ),
        patch(
            "app.api.routes.messages.telemetry_common.connect_to_device",
            new=AsyncMock(return_value=meshcore_mock),
        ),
        # Shrink the timeout so the test doesn't actually sleep 10 s.
        patch(
            "app.api.routes.messages.asyncio.wait_for", side_effect=asyncio.TimeoutError
        ),
    ):
        try:
            response = client.post(
                "/api/messages",
                json={"channel": "#test", "message": "hello"},
                headers={"x-api-token": _VALID_TOKEN},
            )
        finally:
            _remove_token()

    assert response.status_code == 504
    assert "timeout" in response.json()["detail"]["message"].lower()
