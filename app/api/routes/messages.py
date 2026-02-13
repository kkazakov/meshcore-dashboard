"""
POST /api/messages — send a text message to a named channel on the connected
MeshCore companion device.

Authentication
--------------
Requires a valid ``x-api-token`` header obtained from ``POST /api/login``.

Request body
------------
``channel`` : channel name, optionally prefixed with ``#`` (e.g. ``#test``
              or ``test``).  Matching is case-insensitive.
``message``  : UTF-8 text to send.

Responses
---------
- **200** — message queued for transmission; returns the resolved channel index
  and name.
- **400** — empty channel name or empty message.
- **401** — invalid or missing ``x-api-token``.
- **404** — no channel with the given name exists on the device.
- **502** — device connection failed or send was rejected.
- **504** — device did not acknowledge the send within the timeout.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import require_token
from app.meshcore import telemetry_common
from app.meshcore.connection import device_lock
from meshcore import EventType

logger = logging.getLogger(__name__)

router = APIRouter()

# Maximum number of channel slots to probe (matches firmware cap).
_MAX_CHANNEL_SLOTS = 8


# ── Pydantic models ───────────────────────────────────────────────────────────


class SendMessageRequest(BaseModel):
    channel: str
    message: str


class SendMessageResponse(BaseModel):
    status: str
    channel_index: int
    channel_name: str


# ── Internal helpers ──────────────────────────────────────────────────────────


def _strip_hash(channel: str) -> str:
    """Remove a leading ``#`` from a channel name, if present."""
    return channel.lstrip("#")


async def _resolve_channel_index(meshcore, channel_name: str) -> tuple[int, str]:
    """
    Scan device slots 0 – 7 and return ``(index, canonical_name)`` for the
    slot whose name matches *channel_name* (case-insensitive, ``#`` stripped).

    Raises ``HTTPException(404)`` if no matching channel is found.
    """
    needle = _strip_hash(channel_name).lower()

    for idx in range(_MAX_CHANNEL_SLOTS):
        try:
            event = await meshcore.commands.get_channel(idx)
        except Exception as exc:
            logger.warning("Error fetching channel %d: %s", idx, exc)
            break

        if event is None or event.type == EventType.ERROR:
            break

        payload = event.payload
        name: str = payload.get("channel_name", "")
        secret_raw = payload.get("channel_secret", b"")
        secret_hex = (
            secret_raw.hex()
            if isinstance(secret_raw, (bytes, bytearray))
            else str(secret_raw)
        )

        # Skip uninitialised slots.
        if not name and all(c == "0" for c in secret_hex):
            continue

        if _strip_hash(name).lower() == needle:
            return payload.get("channel_idx", idx), name

    raise HTTPException(
        status_code=404,
        detail={
            "status": "error",
            "message": f"Channel '{channel_name}' not found on device",
        },
    )


# ── Route ─────────────────────────────────────────────────────────────────────


@router.post("/api/messages", response_model=SendMessageResponse)
async def send_message(
    payload: SendMessageRequest,
    _email: str = Depends(require_token),
) -> SendMessageResponse:
    """
    Send a text message to a named channel on the connected MeshCore device.

    The ``channel`` field accepts names with or without a leading ``#``
    (e.g. ``"#test"`` and ``"test"`` are equivalent).  Matching against the
    channels configured on the device is case-insensitive.

    - **400** — ``channel`` or ``message`` is empty.
    - **401** — invalid or missing ``x-api-token``.
    - **404** — channel not found on the device.
    - **502** — device connection failed or the send command was rejected.
    - **504** — device did not acknowledge the send.
    """
    channel_name = payload.channel.strip()
    message_text = payload.message.strip()

    if not channel_name:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "channel must not be empty"},
        )
    if not message_text:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "message must not be empty"},
        )

    config = telemetry_common.load_config()
    meshcore = None

    async with device_lock:
        try:
            try:
                meshcore = await telemetry_common.connect_to_device(
                    config, verbose=False
                )
            except Exception as exc:
                logger.error("Failed to connect to MeshCore device: %s", exc)
                raise HTTPException(
                    status_code=502,
                    detail={
                        "status": "error",
                        "message": f"Device connection failed: {exc}",
                    },
                ) from exc

            chan_idx, chan_name = await _resolve_channel_index(meshcore, channel_name)

            logger.info(
                "Sending message to channel '%s' (slot %d): %r",
                chan_name,
                chan_idx,
                message_text,
            )

            try:
                result = await asyncio.wait_for(
                    meshcore.commands.send_chan_msg(chan_idx, message_text),
                    timeout=10,
                )
            except asyncio.TimeoutError as exc:
                logger.error("send_chan_msg timed out for channel '%s'", chan_name)
                raise HTTPException(
                    status_code=504,
                    detail={
                        "status": "error",
                        "message": "Device did not acknowledge the message send (timeout)",
                    },
                ) from exc
            except Exception as exc:
                logger.error("send_chan_msg failed: %s", exc)
                raise HTTPException(
                    status_code=502,
                    detail={
                        "status": "error",
                        "message": f"Failed to send message: {exc}",
                    },
                ) from exc

            if result is None or result.type == EventType.ERROR:
                err_msg = result.payload if result else "no response"
                raise HTTPException(
                    status_code=502,
                    detail={
                        "status": "error",
                        "message": f"Device rejected the message: {err_msg}",
                    },
                )

            return SendMessageResponse(
                status="ok",
                channel_index=chan_idx,
                channel_name=chan_name,
            )

        finally:
            if meshcore:
                try:
                    await asyncio.wait_for(meshcore.disconnect(), timeout=5)
                except Exception:
                    pass
