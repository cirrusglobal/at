"""Authentication layer.

The brief asks for authentication only: *authorization is open to every
authenticated user*. So there are deliberately no roles, scopes, or ownership
checks anywhere in this codebase — `require_auth` is the whole policy.

Tokens are self-issued HS256 JWTs so a reviewer can obtain one with a single
curl and no AWS account. `verify_token` is the single seam to swap for Cognito
in production (RS256 against the pool's JWKS endpoint); see the README.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.config import Settings, get_settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/token")

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def authenticate_user(username: str, password: str, settings: Settings) -> bool:
    """Check credentials against the seeded demo user.

    Both comparisons run unconditionally via compare_digest so the response
    time does not reveal whether the username was the part that was wrong.
    """
    user_ok = secrets.compare_digest(username, settings.demo_username)
    password_ok = secrets.compare_digest(password, settings.demo_password)
    return user_ok and password_ok


def create_access_token(subject: str, settings: Settings) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    ttl = timedelta(minutes=settings.access_token_ttl_minutes)
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + ttl,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(ttl.total_seconds())


def verify_token(token: str, settings: Settings) -> str:
    """Return the subject of a valid token, else raise 401."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            # Pinning the algorithm list is what prevents the `alg: none`
            # and HS256/RS256 confusion attacks.
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.InvalidTokenError:
        # Covers expiry, bad signature, wrong audience/issuer, malformed input.
        # Deliberately not echoing the reason back to the caller.
        raise _UNAUTHENTICATED from None

    subject = claims.get("sub")
    if not subject:
        raise _UNAUTHENTICATED
    return subject


def require_auth(
    token: str = Depends(oauth2_scheme),
    settings: Settings = Depends(get_settings),
) -> str:
    """FastAPI dependency. Returns the authenticated subject."""
    return verify_token(token, settings)
