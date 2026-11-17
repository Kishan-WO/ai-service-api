# Q11. What is JSONResponse vs error response, and `send`?

There's no separate "ErrorResponse" class. An **error response** is a normal response with a 4xx/5xx status code. `JSONResponse` builds it; `send` delivers it.

## JSONResponse
```python
from fastapi.responses import JSONResponse

JSONResponse({"message": "ok"})                                     # 200
JSONResponse({"detail": "Not found"}, status_code=404)              # error
JSONResponse({"detail": "Internal server error"}, status_code=500)  # error
```

## Producing errors in a route
```python
raise HTTPException(status_code=404, detail="User not found")
# or
return JSONResponse({"detail": "User not found"}, status_code=404)
```

## Where `send` comes in
In raw ASGI middleware you don't `return` a response; a response object is an ASGI app, so you **call it**:
```python
try:
    await self.app(scope, receive, send_with_headers)
except Exception:
    response = JSONResponse({"detail": "Internal server error"}, status_code=500)
    await response(scope, receive, send_with_headers)
```
Calling `response(...)` does two `send` calls: `http.response.start` then `http.response.body`.

## Why `send_with_headers`
The error response also gets `X-Request-ID` and `X-Process-Time`, and `status_code` gets recorded for logging.

## Caveat
If `http.response.start` was already sent before the exception, you can't send a second response; the connection just breaks. Handlers often check whether the response has started.
