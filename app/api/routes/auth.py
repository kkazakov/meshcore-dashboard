"""
POST /api/login — password-based authentication.

Tokens are random, opaque strings stored in ClickHouse tokens table.
They expire after 7 days of inactivity.
"""

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.clickhouse import get_client
from app.meshcore import telemetry_common
from meshcore import EventType

logger = logging.getLogger(__name__)

router = APIRouter()

TOKEN_TTL_DAYS = 7


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    email: str
    username: str
    access_rights: str
    device_name: str


@router.post("/api/login", response_model=LoginResponse)
async def login(payload: LoginRequest) -> LoginResponse:
    """
    Authenticate a user by email and password.

    - **email**: the user's email (or login identifier).
    - **password**: plaintext password — compared against the stored bcrypt hash.

    Returns a random opaque **token** (kept in server memory only) together
    with the user's profile.  The token can be passed as
    ``Authorization: Bearer <token>`` on subsequent requests.

    Raises **401** on invalid credentials or inactive account,
    **503** if the database is unreachable.
    """
    client = get_client()

    try:
        result = client.query(
            "SELECT password_hash, username, active, access_rights "
            "FROM users FINAL "
            "WHERE email = {email:String} "
            "LIMIT 1",
            parameters={"email": payload.email},
        )
    except Exception as exc:
        logger.error("ClickHouse query failed during login: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    rows = result.result_rows
    if not rows:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    password_hash, username, active, access_rights = rows[0]

    if not active:
        raise HTTPException(status_code=401, detail="Account is inactive")

    password_matches = bcrypt.checkpw(payload.password.encode(), password_hash.encode())
    if not password_matches:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = secrets.token_hex(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=TOKEN_TTL_DAYS)

    try:
        client.insert(
            "tokens",
            [[token, payload.email, expires_at, expires_at]],
            column_names=["token", "email", "created_at", "expires_at"],
        )
    except Exception as exc:
        logger.error("Failed to store token in ClickHouse: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    logger.info("Issued token for %s (expires %s)", payload.email, expires_at)

    device_name = ""
    meshcore = None
    try:
        config = telemetry_common.load_config()
        meshcore = await telemetry_common.connect_to_device(config, verbose=False)
        result = await meshcore.commands.send_appstart()
        if result and result.type != EventType.ERROR:
            device_name = result.payload.get("name", "")
    except Exception as exc:
        logger.warning("Failed to get device name during login: %s", exc)
    finally:
        if meshcore:
            try:
                await asyncio.wait_for(meshcore.disconnect(), timeout=5)
            except Exception:
                pass

    return LoginResponse(
        token=token,
        email=payload.email,
        username=username,
        access_rights=access_rights,
        device_name=device_name,
    )
