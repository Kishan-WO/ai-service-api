# Q5. Explain this logging line

```python
# Silence overly verbose third-party loggers
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
```

It turns down the noise from Uvicorn's **access log**, so only warnings and errors show instead of every request.

- `logging.getLogger("uvicorn.access")` gets the logger Uvicorn uses to record each HTTP request.
- `.setLevel(logging.WARNING)` ignores anything below `WARNING`.

## Why
By default each request is logged at `INFO`:
```
INFO:     127.0.0.1:52341 - "GET /api/users HTTP/1.1" 200 OK
```
On a busy API (or frequent health checks) these drown out your own logs.

## Levels
`DEBUG < INFO < WARNING < ERROR < CRITICAL`. Access logs are `INFO`, so `WARNING` hides them.

## Things to know
- Only affects `uvicorn.access`; `uvicorn.error` and your own loggers are untouched.
- Typically done in a logging setup function at startup.
- Other candidates: `"sqlalchemy.engine"`, `"httpx"`, `"urllib3"`, `"botocore"`.
- `--no-access-log` disables access logs entirely.
- If you need access logs for auditing, keep `INFO` or log via your own middleware.
