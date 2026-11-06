import httpx

from ai_service.core.config import get_settings

from .conftest import make_pdf, unique_text

UPLOAD_URL = "/api/v1/documents/upload"
LIST_URL = "/api/v1/documents"


async def upload(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    filename: str,
    content: bytes,
    content_type: str = "application/octet-stream",
    **fields: str,
) -> httpx.Response:
    return await client.post(
        UPLOAD_URL, headers=headers, files={"file": (filename, content, content_type)}, data=fields
    )


async def test_upload_txt(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await upload(client, auth_headers, "notes.txt", b"hello world", "text/plain")
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "notes"
    assert body["source"] == "notes.txt"
    assert len(body["content_hash"]) == 64
    assert body["metadata"] == {"file_type": "txt", "byte_size": 11, "content_type": "text/plain"}
    assert "content" not in body  # the text only comes with GET /documents/{id}


async def test_upload_md_with_custom_title(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await upload(
        client, auth_headers, "guide.md", "# नमस्ते\nयह पाठ है".encode(), title="My guide"
    )
    assert response.status_code == 201
    assert response.json()["title"] == "My guide"

    detail = await client.get(f"{LIST_URL}/{response.json()['id']}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["content"] == "# नमस्ते\nयह पाठ है"


async def test_upload_pdf_extracts_text(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await upload(client, auth_headers, "report.pdf", make_pdf("Quarterly revenue grew"))
    assert response.status_code == 201
    assert response.json()["metadata"]["page_count"] == 1

    detail = await client.get(f"{LIST_URL}/{response.json()['id']}", headers=auth_headers)
    assert "Quarterly revenue grew" in detail.json()["content"]


async def test_upload_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.post(UPLOAD_URL, files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 401


async def test_unsupported_file_type(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await upload(client, auth_headers, "image.png", b"\x89PNG")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


async def test_file_over_20_mb_is_rejected_with_413(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    limit = get_settings().MAX_UPLOAD_SIZE_BYTES
    assert limit == 20 * 1024 * 1024
    response = await upload(client, auth_headers, "big.txt", b"a" * (limit + 1))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"

    exactly = await upload(client, auth_headers, "edge.txt", b"a" * limit)
    assert exactly.status_code == 201  # the limit itself is allowed


async def test_invalid_files_are_rejected(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    not_utf8 = await upload(client, auth_headers, "bad.txt", b"\xff\xfe\x00bad")
    assert not_utf8.status_code == 422
    empty = await upload(client, auth_headers, "empty.txt", b"   \n")
    assert empty.status_code == 422
    broken_pdf = await upload(client, auth_headers, "broken.pdf", b"this is not a pdf")
    assert broken_pdf.status_code == 422
    assert broken_pdf.json()["error"]["code"] == "INVALID_DOCUMENT"


async def test_nul_characters_are_removed(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await upload(client, auth_headers, "nul.txt", b"abc\x00def")
    detail = await client.get(f"{LIST_URL}/{response.json()['id']}", headers=auth_headers)
    assert detail.json()["content"] == "abcdef"


async def test_duplicate_content_is_rejected_even_with_a_new_name(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    content = unique_text()
    first = await upload(client, auth_headers, "one.txt", content)
    second = await upload(client, auth_headers, "two.txt", content)
    assert first.status_code == 201
    assert second.status_code == 409
    error = second.json()["error"]
    assert error["code"] == "DUPLICATE_DOCUMENT"
    assert error["details"]["document_id"] == first.json()["id"]


async def test_pagination(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = []
    for number in range(5):
        response = await upload(client, auth_headers, f"doc{number}.txt", unique_text(str(number)))
        ids.append(response.json()["id"])

    first = (await client.get(LIST_URL, params={"limit": 2}, headers=auth_headers)).json()
    assert first["total"] == 5 and first["limit"] == 2 and first["offset"] == 0
    assert len(first["items"]) == 2

    second = (
        await client.get(LIST_URL, params={"limit": 2, "offset": 2}, headers=auth_headers)
    ).json()
    last = (
        await client.get(LIST_URL, params={"limit": 2, "offset": 4}, headers=auth_headers)
    ).json()
    assert len(second["items"]) == 2 and len(last["items"]) == 1

    seen = [item["id"] for page in (first, second, last) for item in page["items"]]
    assert sorted(seen) == sorted(ids)  # every document exactly once across the pages
    assert (await client.get(LIST_URL, params={"offset": 99}, headers=auth_headers)).json()[
        "items"
    ] == []


async def test_pagination_limits_are_validated(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        response = await client.get(LIST_URL, params=params, headers=auth_headers)
        assert response.status_code == 422, params


async def test_get_and_delete(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    created = (await upload(client, auth_headers, "x.txt", unique_text())).json()
    url = f"{LIST_URL}/{created['id']}"

    assert (await client.get(url, headers=auth_headers)).status_code == 200
    assert (await client.delete(url, headers=auth_headers)).status_code == 204
    assert (await client.get(url, headers=auth_headers)).status_code == 404
    assert (await client.delete(url, headers=auth_headers)).status_code == 404

    # after deleting, the same content can be uploaded again
    again = await upload(client, auth_headers, "x.txt", b"fresh")
    assert again.status_code == 201


async def test_malformed_id_is_a_validation_error(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get(f"{LIST_URL}/not-a-uuid", headers=auth_headers)
    assert response.status_code == 422
