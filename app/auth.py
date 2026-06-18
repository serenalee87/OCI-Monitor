"""
Authentication module — signed-cookie session management.
No extra dependencies: uses stdlib hmac + hashlib + secrets.
"""
import hmac
import hashlib
import secrets
import time
from typing import Optional

from app.config import settings

COOKIE_NAME = "oci_monitor_session"
COOKIE_MAX_AGE = 86400 * 7  # 7 days
SIGNATURE_DELIMITER = "."


def _get_secret_key() -> str:
    """Return the secret key, falling back to WEB_PASSWORD if not set."""
    return settings.SECRET_KEY or settings.WEB_PASSWORD or "oci-monitor-fallback-key"


def create_session_token(username: str) -> str:
    """Create a signed session token: username.timestamp.signature"""
    secret = _get_secret_key()
    payload = f"{username}{SIGNATURE_DELIMITER}{int(time.time())}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}{SIGNATURE_DELIMITER}{sig}"


def verify_session_token(token: str) -> Optional[str]:
    """
    Verify a session token. Returns the username if valid, None otherwise.
    """
    if not token:
        return None

    parts = token.split(SIGNATURE_DELIMITER)
    if len(parts) != 3:
        return None

    username, ts_str, sig = parts

    # Verify username is valid
    valid_users = _get_valid_users()
    if username not in valid_users:
        return None

    # Verify signature
    secret = _get_secret_key()
    payload = f"{username}{SIGNATURE_DELIMITER}{ts_str}"
    expected_sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]

    if not hmac.compare_digest(sig, expected_sig):
        return None

    # Check expiry
    try:
        ts = int(ts_str)
    except ValueError:
        return None

    if time.time() - ts > COOKIE_MAX_AGE:
        return None

    return username


def authenticate_user(username: str, password: str) -> bool:
    """Check if username and password are valid."""
    valid_users = _get_valid_users()
    if username in valid_users:
        return hmac.compare_digest(valid_users[username], password)
    return False


def _get_valid_users() -> dict:
    """Build the valid users dict from config."""
    users = {}
    if settings.WEB_USERNAME and settings.WEB_PASSWORD:
        users[settings.WEB_USERNAME] = settings.WEB_PASSWORD
    return users


def is_auth_required() -> bool:
    """Check if authentication is configured (has both username and password)."""
    return bool(settings.WEB_USERNAME and settings.WEB_PASSWORD)
