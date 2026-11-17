# Q34. Explain the `RateLimiter` class

> **Update (Day 6):** The `asyncio.Lock` shown below (`_lock`, the `async with self._lock:` line, and the section "Why the lock") was **removed** after a follow-up question: it was not needed for correctness, because the check and the append have no `await` between them and the loop re-checks after every sleep. The rest of this answer (sliding window, `clock` and `sleep` injection) is still correct. See [08-limited-client-and-the-rate-limiter-lock.md](08-limited-client-and-the-rate-limiter-lock.md) for the lock questions, and the current code in `src/ai_service/services/llm_wrappers.py`.

```python
class RateLimiter:
    def __init__(self, per_minute: int, *, clock=time.monotonic, sleep=asyncio.sleep) -> None:
        self._per_minute = per_minute
        self._clock = clock
        self._sleep = sleep
        self._starts: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                while self._starts and now - self._starts[0] >= 60:
                    self._starts.popleft()
                if len(self._starts) < self._per_minute:
                    self._starts.append(now)
                    return
                await self._sleep(self._starts[0] + 60 - now)
```

## What it does
Ensures **no more than `per_minute` calls start within any 60 seconds**. Over the limit, `acquire()` **waits** instead of rejecting.
```python
limiter = RateLimiter(per_minute=60)
await limiter.acquire()
return await client.chat.completions.create(...)
```

## State
- `_starts`: deque of recent call start times (oldest left, newest right).
- `_lock`: one caller runs `acquire` at a time.

## Algorithm (sliding window)
1. **Forget old calls**: drop timestamps >= 60s old.
2. **Room?** If fewer than `per_minute`, record `now` and return.
3. **Otherwise wait** until the oldest turns 60s old: `starts[0] + 60 - now`, then loop and re-check.

Example, `per_minute=3`:
```
t=0   A -> [0]
t=5   B -> [0, 5]
t=10  C -> [0, 5, 10]
t=12  D -> full, sleep 0+60-12 = 48s
t=60  wake, 0 dropped -> [5, 10], append 60
```

## Why `while True`
After waking, state may have changed; re-check rather than assume.

## Why the lock
- **Correctness:** two coroutines can't both take the last slot.
- **Fairness:** held **during the sleep**; asyncio locks are FIFO, so waiters are served in order.

## Why inject `clock` and `sleep`
Dependency injection for tests (fake clock/sleep, no real waiting). `time.monotonic` never goes backwards when the system clock changes.

## Things to know
- Sliding window avoids the 2x burst at fixed-window boundaries.
- Limits call *starts*, not concurrency (use `asyncio.Semaphore` for that).
- Single-process only; multiple workers need e.g. Redis.
- Memory bounded by `per_minute`.
- Cancellation is safe: lock released, no slot recorded.
