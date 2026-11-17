# Q31. How is `RateLimitedError` used, and how do parent constructor params get passed?

```python
class LLMError(Exception):
    retryable = False
    fallback_ok = False

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after

    @property
    def kind(self) -> str:
        return type(self).__name__


class RateLimitedError(LLMError):
    retryable = True
    fallback_ok = True
```

## Why no parent constructor call is needed
`RateLimitedError` defines no `__init__`, so Python **inherits `LLMError.__init__`** (first `__init__` found in the MRO).
```python
err = RateLimitedError("Too many requests", retry_after=12.0)
```
runs `LLMError.__init__`, which sets the message and `retry_after`. You only write `super().__init__(...)` when a subclass defines its **own** `__init__`. Here the subclass only overrides class attributes:
```python
RateLimitedError("x").retryable   # True
LLMError("x").retryable           # False
RateLimitedError("x").kind        # "RateLimitedError"
```

## Where it's raised
In the provider adapter, translate vendor SDK errors:
```python
except anthropic.RateLimitError as exc:
    raise RateLimitedError("provider rate limited", retry_after=_parse_retry_after(exc)) from exc
except anthropic.APIError as exc:
    raise LLMError("provider failed") from exc
```
`from exc` chains the original error.

## How it's caught
1. Base class catches everything: `except (LLMError, StopAsyncIteration) as exc: raise LLMUnavailableError() from exc`; `chat_stream` has `except LLMError`.
2. Retry/fallback via flags:
```python
except LLMError as exc:
    if not exc.fallback_ok:
        raise
    continue   # try next provider
```
```python
if exc.retryable:
    await asyncio.sleep(exc.retry_after or 1.0)
```
3. HTTP layer: `{"Retry-After": str(int(exc.retry_after))}`.

| Error | retryable | fallback_ok | Reasoning |
|---|---|---|---|
| `RateLimitedError` | yes | yes | wait/retry or other provider |
| overloaded/timeout | yes | yes | transient |
| auth/bad request | no | no | won't help |
| provider outage | no | yes | another provider may work |

## Caveat
Retrying is only safe **before** any token has been streamed; hence the route fetches the first event up front.
