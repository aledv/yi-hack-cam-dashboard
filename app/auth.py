"""Minimal single-user auth: signed session cookie + bcrypt password check.
No JWT/OAuth/2FA -- deliberately simple, this app is LAN-only."""

import os

import bcrypt
from fastapi import Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


def _unescape_dollar(value: str) -> str:
    """.env stores secrets `$$`-escaped for Docker Compose's env_file
    interpolation (see hash_password.py). Compose undoes that escaping
    before the container ever sees it, but python-dotenv's load_dotenv()
    (used for local, non-Docker runs) doesn't -- so outside Docker these
    values arrive here still doubled. Undoing it explicitly makes both
    paths work: a no-op in Docker (already single `$`), the fix locally.
    """
    return value.replace("$$", "$")


SECRET_KEY = _unescape_dollar(os.environ["SECRET_KEY"])
ADMIN_USER = os.environ["ADMIN_USER"]
ADMIN_PASSWORD_HASH = _unescape_dollar(os.environ["ADMIN_PASSWORD_HASH"]).encode()

SESSION_COOKIE = "session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

_serializer = URLSafeTimedSerializer(SECRET_KEY)


def verify_credentials(username: str, password: str) -> bool:
    if username != ADMIN_USER:
        return False
    return bcrypt.checkpw(password.encode(), ADMIN_PASSWORD_HASH)


def create_session_cookie() -> str:
    return _serializer.dumps({"user": ADMIN_USER})


def is_logged_in(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    try:
        _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def require_login(request: Request):
    """Dependency: redirects to /login if not authenticated."""
    if not is_logged_in(request):
        return RedirectResponse(url="/login", status_code=303)
    return None
