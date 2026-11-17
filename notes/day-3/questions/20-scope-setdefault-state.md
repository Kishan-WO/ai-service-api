# Q9. Explain the `setdefault("state", {})` line

```python
incoming = MutableHeaders(scope=scope).get(REQUEST_ID_HEADER, "")
request_id = incoming if _SAFE_REQUEST_ID.fullmatch(incoming) else str(uuid.uuid4())
state: dict[str, Any] = scope.setdefault("state", {})
state["request_id"] = request_id
```

It gets (or creates) a per-request dictionary inside the ASGI `scope`.

- **`scope`**: ASGI dict describing the request, shared by middleware and framework.
- **`dict.setdefault(key, default)`**: if `"state"` exists, returns it; otherwise inserts `{}` and returns it.
- **`state: dict[str, Any]`**: a type hint.

Equivalent to:
```python
if "state" not in scope:
    scope["state"] = {}
state = scope["state"]
```

## Why `setdefault`
Overwriting would wipe data earlier middleware (or lifespan state) stored. `setdefault` preserves it.

## What next
`state["request_id"] = request_id` writes to the same dict; Starlette's `request.state` is backed by `scope["state"]`:
```python
@app.get("/")
async def index(request: Request):
    return {"request_id": request.state.request_id}
```

## The lines above
- First reads the request ID header (e.g. `X-Request-ID`), default `""`.
- Second validates it against a regex: reuse if safe, else generate a UUID. This prevents log injection from untrusted headers while still allowing cross-service tracing.
