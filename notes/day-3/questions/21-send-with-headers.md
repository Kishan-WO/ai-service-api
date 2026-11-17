# Q10. Explain `send_with_headers` (especially the `http.response.start` block)

```python
async def send_with_headers(message: Message) -> None:
    nonlocal status_code
    if message["type"] == "http.response.start":
        status_code = message["status"]
        headers = MutableHeaders(scope=message)
        headers[REQUEST_ID_HEADER] = request_id
        headers["X-Process-Time"] = f"{(time.perf_counter() - start) * 1000:.2f}ms"
    await send(message)

try:
    await self.app(scope, receive, send_with_headers)
```

This block **intercepts the outgoing response**, captures the status code, and adds two headers (request ID, processing time).

## Background: ASGI sends in pieces
1. `{"type": "http.response.start", "status": 200, "headers": [...]}`
2. `{"type": "http.response.body", "body": b"...", "more_body": False}`

Headers can only be modified in the **first** message.

## Line by line
- `if message["type"] == "http.response.start"`: only act on the status/headers message.
- `status_code = message["status"]`: saved to the outer variable (`nonlocal` allows assignment) so the logger can use it later.
- `MutableHeaders(scope=message)`: wraps the raw header list in the message; it also has a `"headers"` key. Edits modify `message["headers"]` in place.
- `headers[REQUEST_ID_HEADER] = request_id`: lets clients/proxies correlate with your logs.
- `headers["X-Process-Time"] = ...`: `perf_counter()` difference since `start`, `* 1000` → ms, `:.2f` → 2 decimals.
- `await send(message)`: forwards the modified message.

## How the wrapper is used
`await self.app(scope, receive, send_with_headers)` passes the wrapper **instead of** the original `send` (like Express `next()`). When FastAPI sends its response it calls your wrapper first.

## Note
Process time is measured until the response **starts**, not until the body is fully sent (streaming responses take longer).
