import datetime

import httpx
import jwt

from ai_service.core.config import get_settings
from ai_service.core.security import create_access_token

from .conftest import PASSWORD, REGISTER_URL, Registrar

LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"


async def test_register_returns_a_working_token(client: httpx.AsyncClient) -> None:
    response = await client.post(
        REGISTER_URL,
        json={"email": "Ana@Example.com", "password": PASSWORD, "tenant_name": "Acme"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().ACCESS_TOKEN_EXPIRE_MINUTES * 60

    me = await client.get(ME_URL, headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "ana@example.com"  # stored lower-case
    assert me.json()["tenant"]["name"] == "Acme"


async def test_token_contains_user_and_tenant(client: httpx.AsyncClient) -> None:
    response = await client.post(
        REGISTER_URL, json={"email": "a@example.com", "password": PASSWORD, "tenant_name": "T"}
    )
    claims = jwt.decode(response.json()["access_token"], options={"verify_signature": False})
    assert {"sub", "tenant_id", "exp", "iat"} <= claims.keys()


async def test_duplicate_email_is_rejected(client: httpx.AsyncClient) -> None:
    payload = {"email": "dup@example.com", "password": PASSWORD, "tenant_name": "T"}
    assert (await client.post(REGISTER_URL, json=payload)).status_code == 201
    second = await client.post(REGISTER_URL, json={**payload, "email": "DUP@example.com"})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


async def test_register_validates_input(client: httpx.AsyncClient) -> None:
    response = await client.post(
        REGISTER_URL, json={"email": "not-an-email", "password": "short", "tenant_name": ""}
    )
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    fields = {detail["location"][-1] for detail in body["details"]}
    assert fields == {"email", "password", "tenant_name"}


async def test_login_with_correct_credentials(
    client: httpx.AsyncClient, register: Registrar
) -> None:
    await register("login@example.com")
    response = await client.post(
        LOGIN_URL, json={"email": "login@example.com", "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_login_failures_look_the_same(client: httpx.AsyncClient, register: Registrar) -> None:
    await register("real@example.com")
    wrong_password = await client.post(
        LOGIN_URL, json={"email": "real@example.com", "password": "nope-nope"}
    )
    unknown_email = await client.post(
        LOGIN_URL, json={"email": "ghost@example.com", "password": PASSWORD}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]


async def test_oauth2_form_login_for_swagger(
    client: httpx.AsyncClient, register: Registrar
) -> None:
    await register("form@example.com")
    response = await client.post(
        "/api/v1/auth/token", data={"username": "form@example.com", "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


async def test_me_requires_a_valid_token(client: httpx.AsyncClient) -> None:
    missing = await client.get(ME_URL)
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert missing.json()["error"]["code"] == "NOT_AUTHENTICATED"

    garbage = await client.get(ME_URL, headers={"Authorization": "Bearer not.a.token"})
    assert garbage.status_code == 401


async def test_token_signed_with_another_key_is_rejected(client: httpx.AsyncClient) -> None:
    forged = jwt.encode(
        {"sub": "x", "tenant_id": "y", "iat": 1, "exp": 4102444800},
        "another-key-" * 4,
        algorithm="HS256",
    )
    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


async def test_expired_token_is_rejected(client: httpx.AsyncClient, register: Registrar) -> None:
    headers = await register("old@example.com")
    claims = jwt.decode(headers["Authorization"].split()[1], options={"verify_signature": False})
    expired = create_access_token(
        {"sub": claims["sub"], "tenant_id": claims["tenant_id"]},
        expires_delta=datetime.timedelta(seconds=-5),
    )
    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


async def test_token_with_someone_elses_tenant_is_rejected(
    client: httpx.AsyncClient, register: Registrar
) -> None:
    """The tenant claim must match the user's real tenant, so it cannot be swapped."""
    headers_a = await register("a@example.com")
    headers_b = await register("b@example.com")
    claims_a = jwt.decode(
        headers_a["Authorization"].split()[1], options={"verify_signature": False}
    )
    claims_b = jwt.decode(
        headers_b["Authorization"].split()[1], options={"verify_signature": False}
    )
    forged = create_access_token({"sub": claims_a["sub"], "tenant_id": claims_b["tenant_id"]})
    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401
