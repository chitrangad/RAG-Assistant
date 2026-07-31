"""Simple file-based authentication for the admin panel.

Reads credentials from a text file (format: ``username:hash`` per line).
Uses SHA-256 with per-password salt for hashing and signed session tokens.
"""

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from src.config import settings
from src.logging_config import get_logger

logger = get_logger(__name__)

# ── Paths ──────────────────────────────────────────────────────────
CREDENTIALS_FILE = settings.data_dir / ".credentials"
SESSION_SECRET_FILE = settings.data_dir / ".session_secret"

# ── Token expiry: 8 hours ─────────────────────────────────────────
SESSION_TTL = 8 * 3600

# ── Internal: load / save ──────────────────────────────────────────


def _get_or_create_secret() -> bytes:
    """Load or create a random 32-byte secret for signing session tokens."""
    if SESSION_SECRET_FILE.exists():
        return SESSION_SECRET_FILE.read_bytes()
    secret = secrets.token_bytes(32)
    SESSION_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_SECRET_FILE.write_bytes(secret)
    # Restrict permissions on POSIX
    try:
        os.chmod(SESSION_SECRET_FILE, 0o600)
    except OSError:
        pass
    return secret


def _load_credentials() -> dict[str, str]:
    """Parse the credentials file into {username: hash}."""
    if not CREDENTIALS_FILE.exists():
        logger.warning("credentials_file_missing", path=str(CREDENTIALS_FILE))
        return {}

    creds: dict[str, str] = {}
    for raw in CREDENTIALS_FILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        user, _, pwd_hash = line.partition(":")
        creds[user.strip()] = pwd_hash.strip()

    logger.info("credentials_loaded", user_count=len(creds))
    return creds


# ── Password hashing ───────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Hash a password with a random 16-byte salt."""
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"sha256${salt}${h}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Check a password against a stored hash."""
    if not stored_hash.startswith("sha256$"):
        # Legacy plaintext or unknown format — reject
        return False
    parts = stored_hash.split("$", 2)
    if len(parts) != 3:
        return False
    _, salt, expected = parts
    actual = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return hmac.compare_digest(actual, expected)


# ── Session tokens ─────────────────────────────────────────────────


def _sign(payload: str) -> str:
    secret = _get_or_create_secret()
    sig = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify(token: str) -> str | None:
    """Return the payload if the token is valid, or None."""
    if "." not in token:
        return None
    payload, _, sig = token.partition(".")
    expected = _sign(payload)
    if not hmac.compare_digest(f"{payload}.{sig}", expected):
        return None
    # Check expiry
    try:
        ts_str, username = payload.split(":", 1)
        ts = int(ts_str)
    except (ValueError, TypeError):
        return None
    if time.time() - ts > SESSION_TTL:
        return None
    return username


def create_session_token(username: str) -> str:
    """Create a signed session token for the given user."""
    payload = f"{int(time.time())}:{username}"
    return _sign(payload)


# ── FastAPI dependency ─────────────────────────────────────────────


async def require_admin(
    request: Request,
    admin_session: str | None = Cookie(default=None),
) -> str:
    """FastAPI dependency — returns the authenticated username or raises 401."""
    if not admin_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    username = _verify(admin_session)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    # Verify the user still exists in credentials
    creds = _load_credentials()
    if username not in creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer authorised",
        )

    return username


async def require_admin_page(
    request: Request,
):
    """Dependency for the admin HTML page — redirects to login instead of 401."""
    admin_session = request.cookies.get("admin_session")
    if not admin_session:
        return RedirectResponse(url="/admin/login?next=/admin", status_code=303)

    username = _verify(admin_session)
    if username is None:
        return RedirectResponse(url="/admin/login?next=/admin", status_code=303)

    creds = _load_credentials()
    if username not in creds:
        return RedirectResponse(url="/admin/login?next=/admin", status_code=303)

    return username  # authenticated


# ── Login helper ───────────────────────────────────────────────────


async def authenticate_and_login(username: str, password: str) -> str | None:
    """Validate credentials and return a session token, or None."""
    creds = _load_credentials()
    stored_hash = creds.get(username)
    if stored_hash is None:
        return None
    if not verify_password(password, stored_hash):
        return None
    return create_session_token(username)


# ── CLI helper: generate a credential line ─────────────────────────


def generate_credential_line(username: str, password: str) -> str:
    """Return a line suitable for the credentials file."""
    return f"{username}:{hash_password(password)}"
