import json
import logging

import httpx
import pytest
from fastapi import FastAPI


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_every_response_has_a_request_id_and_timing(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert len(response.headers["x-request-id"]) == 36  # a generated UUID
    assert response.headers["x-process-time"].endswith("ms")
    other = await client.get("/health")
    assert other.headers["x-request-id"] != response.headers["x-request-id"]


async def test_a_client_supplied_request_id_is_kept(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "trace-abc.123"})
    assert response.headers["x-request-id"] == "trace-abc.123"


async def test_an_unsafe_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    for bad in ("x" * 200, 'has spaces and "quotes"'):
        response = await client.get("/health", headers={"X-Request-ID": bad})
        assert response.headers["x-request-id"] != bad
        assert len(response.headers["x-request-id"]) == 36


async def test_not_found_uses_the_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/nope", headers={"X-Request-ID": "req-1"})
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "Not Found", "request_id": "req-1"}
    }


async def test_wrong_method_uses_the_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.post("/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


async def test_unexpected_errors_do_not_leak_details(app: FastAPI) -> None:
    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/boom", headers={"X-Request-ID": "req-500"})

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Internal server error.",
            "request_id": "req-500",
        }
    }
    assert "secret" not in response.text
    assert response.headers["x-request-id"] == "req-500"


async def test_each_request_is_logged_as_json_with_tenant(
    client: httpx.AsyncClient, auth_headers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="ai_service.request"):
        await client.get("/api/v1/auth/me", headers={**auth_headers, "X-Request-ID": "log-1"})

    record = next(r for r in caplog.records if getattr(r, "request_id", None) == "log-1")
    assert record.method == "GET"  # type: ignore[attr-defined]
    assert record.status_code == 200  # type: ignore[attr-defined]
    assert record.path == "/api/v1/auth/me"  # type: ignore[attr-defined]
    assert record.tenant_id  # type: ignore[attr-defined]
    assert record.duration_ms >= 0  # type: ignore[attr-defined]

    # and the JSON formatter turns it into one parseable line
    from ai_service.core.logging import JSONFormatter

    line = json.loads(JSONFormatter().format(record))
    assert line["request_id"] == "log-1" and line["status_code"] == 200
