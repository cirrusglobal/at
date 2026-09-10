"""The authentication layer. Authorization is intentionally not tested: the
brief specifies it is open to every authenticated user, so there is no policy
beyond 'has a valid token'."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest


def test_token_issued_for_valid_credentials(client, settings):
    response = client.post(
        "/v1/auth/token",
        data={"username": settings.demo_username, "password": settings.demo_password},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.access_token_ttl_minutes * 60
    assert body["access_token"]


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("demo", "wrong"),
        ("nobody", "demo-password"),
        ("DEMO", "demo-password"),  # usernames are case-sensitive
        ("demo", "demo-password "),  # no whitespace trimming
    ],
)
def test_bad_credentials_rejected(client, username, password):
    response = client.post("/v1/auth/token", data={"username": username, "password": password})
    assert response.status_code == 401
    # Same message either way — never reveal which half was wrong.
    assert response.json()["detail"] == "Incorrect username or password"


def test_missing_credential_fields_rejected(client):
    response = client.post("/v1/auth/token", data={})
    assert response.status_code == 422


def test_health_is_unauthenticated(client):
    assert client.get("/health").status_code == 200


def test_protected_route_requires_token(client):
    assert client.get("/v1/networks").status_code == 401


def test_garbage_token_rejected(client):
    response = client.get("/v1/networks", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_token_signed_with_wrong_secret_rejected(client, settings):
    forged = jwt.encode(
        {
            "sub": "attacker",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        "not-the-real-secret",
        algorithm="HS256",
    )
    response = client.get("/v1/networks", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_expired_token_rejected(client, settings):
    expired = jwt.encode(
        {
            "sub": settings.demo_username,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    response = client.get("/v1/networks", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_token_for_wrong_audience_rejected(client, settings):
    wrong_audience = jwt.encode(
        {
            "sub": settings.demo_username,
            "iss": settings.jwt_issuer,
            "aud": "some-other-service",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    response = client.get("/v1/networks", headers={"Authorization": f"Bearer {wrong_audience}"})
    assert response.status_code == 401


def test_valid_token_grants_access(client, auth):
    assert client.get("/v1/networks", headers=auth).status_code == 200
