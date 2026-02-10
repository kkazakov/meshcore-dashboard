"""
GET  /api/channels — list channels configured on the connected companion device.
POST /api/channels — create a new channel on the next free slot.

Authentication
--------------
Both endpoints require a valid ``x-api-token`` header obtained from
``POST /api/login``.

Each channel entry contains:
- ``index``        : channel slot index on the device
- ``name``         : human-readable channel name
- ``secret_hex``   : 16-byte channel secret encoded as a hex string
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import require_token
from app.meshcore import telemetry_common
from meshcore import EventType

logger = logging.getLogger(__name__)

router = APIRouter()

# Maximum number of channel slots to probe.  MeshCore firmware caps at 8.
_MAX_CHANNEL_SLOTS = 8


# ── Pydantic models ───────────────────────────────────────────────────────────


class ChannelInfo(BaseModel):
    index: int
    name: str
    secret_hex: str


class ChannelsResponse(BaseModel):
    status: str
    channels: list[ChannelInfo]


class CreateChannelRequest(BaseModel):
    name: str
    password: str | None = None


# ── Internal helpers ──────────────────────────────────────────────────────────


def _is_empty_slot(name: str, secret_hex: str) -> bool:
    """Return True for uninitialised device slots (blank name + zero secret)."""
    return not name and all(c == "0" for c in secret_hex)


async def _fetch_all_channels(meshcore: Any) -> list[dict[str, Any]]:
    """
    Iterate all channel slots on the device and return initialised ones.

    Reads up to ``_MAX_CHANNEL_SLOTS`` indices; empty/uninitialised slots are
    skipped.  Stops early if the device returns ERROR (no more slots).
    """
    channels: list[dict[str, Any]] = []

    for idx in range(_MAX_CHANNEL_SLOTS):
        try:
            event = await meshcore.commands.get_channel(idx)
        except Exception as exc:
            logger.warning("Error fetching channel %d: %s", idx, exc)
            break

        if event is None or event.type == EventType.ERROR:
            break

        payload = event.payload
        secret_raw = payload.get("channel_secret", b"")
        secret_hex = (
            secret_raw.hex()
            if isinstance(secret_raw, (bytes, bytearray))
            else str(secret_raw)
        )
        name = payload.get("channel_name", "")

        if _is_empty_slot(name, secret_hex):
            continue

        channels.append(
            {
                "index": payload.get("channel_idx", idx),
                "name": name,
                "secret_hex": secret_hex,
            }
        )

    return channels


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/api/channels", response_model=ChannelsResponse)
async def get_channels(
    _email: str = Depends(require_token),
) -> ChannelsResponse:
    """
    Return the list of channels configured on the connected MeshCore companion
    device.

    Iterates channel indices 0 – 7; uninitialised slots are omitted.

    - **401** — invalid or missing ``x-api-token``.
    - **502** — device connection failed.

    Example response:

    ```json
    {
      "status": "ok",
      "channels": [
        { "index": 0, "name": "General", "secret_hex": "0a1b2c..." },
        { "index": 1, "name": "Admin",   "secret_hex": "ff00aa..." }
      ]
    }
    ```
    """
    config = telemetry_common.load_config()
    meshcore = None

    try:
        try:
            meshcore = await telemetry_common.connect_to_device(config, verbose=False)
        except Exception as exc:
            logger.error("Failed to connect to MeshCore device: %s", exc)
            raise HTTPException(
                status_code=502,
                detail={
                    "status": "error",
                    "message": f"Device connection failed: {exc}",
                },
            ) from exc

        channels = await _fetch_all_channels(meshcore)

        if not channels:
            logger.info("No channels found on the connected device")

        return ChannelsResponse(
            status="ok",
            channels=[ChannelInfo(**ch) for ch in channels],
        )

    finally:
        if meshcore:
            try:
                await asyncio.wait_for(meshcore.disconnect(), timeout=5)
            except Exception:
                pass


@router.post("/api/channels", response_model=ChannelsResponse, status_code=201)
async def create_channel(
    payload: CreateChannelRequest,
    _email: str = Depends(require_token),
) -> ChannelsResponse:
    """
    Create a new channel on the next free slot of the connected MeshCore
    companion device.

    The channel secret is derived automatically from the name (SHA-256 of the
    name, first 16 bytes — the same algorithm used by MeshCore firmware).

    - **400** — no free slot available (all 8 slots are occupied).
    - **409** — a channel with the same name already exists.
    - **401** — invalid or missing ``x-api-token``.
    - **502** — device connection failed.
    - **504** — device did not acknowledge the write.

    Example request:

    ```json
    { "name": "MyChannel" }
    ```

    Example response (201):

    ```json
    {
      "status": "ok",
      "channels": [
        { "index": 0, "name": "General",   "secret_hex": "0a1b2c..." },
        { "index": 1, "name": "MyChannel", "secret_hex": "ff00aa..." }
      ]
    }
    ```
    """
    channel_name = payload.name.strip()
    if not channel_name:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Channel name must not be empty"},
        )

    config = telemetry_common.load_config()
    meshcore = None

    try:
        try:
            meshcore = await telemetry_common.connect_to_device(config, verbose=False)
        except Exception as exc:
            logger.error("Failed to connect to MeshCore device: %s", exc)
            raise HTTPException(
                status_code=502,
                detail={
                    "status": "error",
                    "message": f"Device connection failed: {exc}",
                },
            ) from exc

        # Read all slots (initialised and raw) to find duplicates and free slots.
        existing: list[dict[str, Any]] = []
        free_slot: int | None = None

        for idx in range(_MAX_CHANNEL_SLOTS):
            try:
                event = await meshcore.commands.get_channel(idx)
            except Exception as exc:
                logger.warning("Error fetching channel %d: %s", idx, exc)
                break

            if event is None or event.type == EventType.ERROR:
                break

            slot_payload = event.payload
            secret_raw = slot_payload.get("channel_secret", b"")
            secret_hex = (
                secret_raw.hex()
                if isinstance(secret_raw, (bytes, bytearray))
                else str(secret_raw)
            )
            name = slot_payload.get("channel_name", "")

            if _is_empty_slot(name, secret_hex):
                # First uninitialised slot becomes the target
                if free_slot is None:
                    free_slot = idx
                continue

            # Duplicate name check (case-insensitive)
            if name.lower() == channel_name.lower():
                raise HTTPException(
                    status_code=409,
                    detail={
                        "status": "error",
                        "message": f"Channel '{name}' already exists at index {idx}",
                    },
                )

            existing.append(
                {
                    "index": slot_payload.get("channel_idx", idx),
                    "name": name,
                    "secret_hex": secret_hex,
                }
            )

        if free_slot is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "status": "error",
                    "message": "No free channel slot available (all 8 slots are occupied)",
                },
            )

        # Write the new channel — secret auto-derived from name by the library
        logger.info("Creating channel '%s' at slot %d", channel_name, free_slot)
        try:
            result = await meshcore.commands.set_channel(free_slot, channel_name)
        except Exception as exc:
            logger.error("set_channel failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail={
                    "status": "error",
                    "message": f"Failed to write channel: {exc}",
                },
            ) from exc

        if result is None or result.type == EventType.ERROR:
            err_msg = result.payload if result else "no response"
            raise HTTPException(
                status_code=504,
                detail={
                    "status": "error",
                    "message": f"Device did not acknowledge channel creation: {err_msg}",
                },
            )

        # Re-read the full channel list so the response reflects device state
        channels = await _fetch_all_channels(meshcore)

        return ChannelsResponse(
            status="ok",
            channels=[ChannelInfo(**ch) for ch in channels],
        )

    finally:
        if meshcore:
            try:
                await asyncio.wait_for(meshcore.disconnect(), timeout=5)
            except Exception:
                pass
