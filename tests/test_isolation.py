"""The core rule: a tenant can never see, read or delete another tenant's documents."""

import uuid

import httpx

from .conftest import Registrar, unique_text

UPLOAD_URL = "/api/v1/documents/upload"
LIST_URL = "/api/v1/documents"


async def upload(
    client: httpx.AsyncClient, headers: dict[str, str], name: str, content: bytes
) -> str:
    response = await client.post(
        UPLOAD_URL, headers=headers, files={"file": (name, content, "text/plain")}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_tenants_cannot_see_each_others_documents(
    client: httpx.AsyncClient, register: Registrar
) -> None:
    headers_1 = await register("user1@tenant1.com")
    headers_2 = await register("user2@tenant2.com")
    doc_1 = await upload(client, headers_1, "one.txt", unique_text("one"))
    doc_2 = await upload(client, headers_2, "two.txt", unique_text("two"))

    # list: each tenant sees only its own document
    list_1 = (await client.get(LIST_URL, headers=headers_1)).json()
    list_2 = (await client.get(LIST_URL, headers=headers_2)).json()
    assert [d["id"] for d in list_1["items"]] == [doc_1] and list_1["total"] == 1
    assert [d["id"] for d in list_2["items"]] == [doc_2] and list_2["total"] == 1

    # read and delete across tenants, in both directions: always 404
    for headers, other_doc in ((headers_1, doc_2), (headers_2, doc_1)):
        read = await client.get(f"{LIST_URL}/{other_doc}", headers=headers)
        delete = await client.delete(f"{LIST_URL}/{other_doc}", headers=headers)
        assert read.status_code == 404
        assert delete.status_code == 404
        assert read.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"

    # the failed deletes changed nothing
    assert (await client.get(f"{LIST_URL}/{doc_1}", headers=headers_1)).status_code == 200
    assert (await client.get(f"{LIST_URL}/{doc_2}", headers=headers_2)).status_code == 200


async def test_another_tenants_document_looks_exactly_like_a_missing_one(
    client: httpx.AsyncClient, register: Registrar
) -> None:
    """Same status and body, so an attacker cannot tell 'exists elsewhere' from 'does not exist'."""
    headers_1 = await register("user1@tenant1.com")
    headers_2 = await register("user2@tenant2.com")
    foreign = await upload(client, headers_2, "secret.txt", unique_text("secret"))

    foreign_response = await client.get(f"{LIST_URL}/{foreign}", headers=headers_1)
    missing_response = await client.get(f"{LIST_URL}/{uuid.uuid4()}", headers=headers_1)
    assert foreign_response.status_code == missing_response.status_code == 404
    assert foreign_response.json()["error"]["code"] == missing_response.json()["error"]["code"]
    assert (
        foreign_response.json()["error"]["message"] == missing_response.json()["error"]["message"]
    )


async def test_same_file_can_be_uploaded_by_two_tenants(
    client: httpx.AsyncClient, register: Registrar
) -> None:
    """(tenant_id, content_hash) is unique per tenant, not globally."""
    headers_1 = await register("user1@tenant1.com")
    headers_2 = await register("user2@tenant2.com")
    content = unique_text("shared")
    id_1 = await upload(client, headers_1, "same.txt", content)
    id_2 = await upload(client, headers_2, "same.txt", content)
    assert id_1 != id_2


async def test_a_tenant_id_in_the_request_is_ignored(
    client: httpx.AsyncClient, register: Registrar
) -> None:
    headers_1 = await register("user1@tenant1.com")
    headers_2 = await register("user2@tenant2.com")
    tenant_2 = (await client.get("/api/v1/auth/me", headers=headers_2)).json()["tenant"]["id"]
    await upload(client, headers_2, "two.txt", unique_text("two"))

    response = await client.get(LIST_URL, params={"tenant_id": tenant_2}, headers=headers_1)
    assert response.json()["total"] == 0


async def test_two_users_registering_get_separate_tenants(
    client: httpx.AsyncClient, register: Registrar
) -> None:
    headers_1 = await register("user1@tenant1.com")
    headers_2 = await register("user2@tenant2.com")
    me_1 = (await client.get("/api/v1/auth/me", headers=headers_1)).json()
    me_2 = (await client.get("/api/v1/auth/me", headers=headers_2)).json()
    assert me_1["tenant"]["id"] != me_2["tenant"]["id"]
