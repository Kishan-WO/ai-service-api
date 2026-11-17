# Q37 to Q40. `LimitedClient`, and the `asyncio.Lock` in the rate limiter

These four questions are one topic (how calls are limited), so they share one file.

| # | What I asked |
|---|---|
| Q37 | "explain this" (pasted the whole `LimitedClient` class) |
| Q38 | "explain me asyncio._lock used in rate limiter?" |
| Q39 | "but who call its lock.acquire()?" |
| Q40 | "but if ai model can handle multiple calls at a time then why we have used this lock, by one checking starts length we can handle concurrency?? so no need to add lock while calling?? asking about self._lock" |

I then said "yes simplify", and the lock was **removed** (answer to Q40 below). The code in this file is shown **after** that change.

**File:** `src/ai_service/services/llm_wrappers.py`

---

# Q37: what does `LimitedClient` do?

It protects one provider from too many calls, with **two limits**:
1. **Concurrency**: at most N calls running at the same time (a semaphore).
2. **Rate**: at most M calls **starting** per minute (the `RateLimiter`, optional).

There is one `LimitedClient` per backend. It wraps another client (`inner`) and lets each call through only when the limits allow.

**Why:** Gemini's free tier allows 15 requests per minute. If 25 requests arrive at once, 10 get a 429. This layer makes the extra requests wait their turn **inside my service**, so most never reach Gemini as a 429. It also protects my own server and the local model from too many parallel calls.

## Line by line
```python
class LimitedClient:
    def __init__(self, inner: LLMClient, *, max_concurrency: int, per_minute: int = 0) -> None:
        self._inner = inner
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._limiter = RateLimiter(per_minute) if per_minute > 0 else None
        self.backend = inner.backend
        self.model = inner.model
```
- `inner`: the client being wrapped.
- The `*` makes `max_concurrency` and `per_minute` keyword-only.
- `asyncio.Semaphore(n)` is a counter of free slots. With `max_concurrency=4`, four calls can run and the fifth waits.
- `per_minute=0` means no per-minute limit, so `_limiter` is `None`.
- `backend` and `model` are copied from the wrapped client so this object still counts as an `LLMClient`.

```python
    async def _start(self) -> None:
        if self._limiter is not None:
            await self._limiter.acquire()
```
Wait for the per-minute limiter if there is one; otherwise do nothing.

```python
    async def generate(self, request):
        async with self._semaphore:
            await self._start()
            return await self._inner.generate(request)
```
1. Take a free slot (wait here if none is free).
2. Wait for the per-minute limiter.
3. Make the real call.
4. The slot is released automatically when the `async with` ends, **even on an error or a cancellation**, so a failed call can never leave a slot stuck.

`generate_structured` is identical.

```python
    async def stream(self, request):
        async with self._semaphore:      # held for the whole stream
            await self._start()
            events = self._inner.stream(request)
            try:
                async for event in events:
                    yield event
            finally:
                await _close(events)
```
For a stream the slot is held from the first event to the last, because the provider is busy for that whole time. `finally: await _close(events)` closes the upstream stream even if the reader stops early, so the slot is freed and the provider stops generating.

## Where it sits
```
Fallback( Retrying( Limited( Accounting( adapter ) ) ) )
```
It is **inside** retry, so every retry attempt also passes the limiter; a burst of retries cannot break the per-minute limit again.

## Two details
- A **semaphore limits how many calls are in flight**, not how many start per minute (a fast call finishes and lets another start). That is why the `RateLimiter` is a separate piece.
- Only `hosted` gets a per-minute limit (`LLM_REQUESTS_PER_MINUTE`). Local and Anthropic use only the concurrency limit.

---

# The `RateLimiter` (what the lock was part of)
```python
class RateLimiter:
    def __init__(self, per_minute, *, clock=time.monotonic, sleep=asyncio.sleep):
        self._per_minute = per_minute
        self._clock = clock
        self._sleep = sleep
        self._starts: deque[float] = deque()      # times of recent call starts

    async def acquire(self) -> None:
        while True:
            now = self._clock()
            while self._starts and now - self._starts[0] >= 60:
                self._starts.popleft()            # forget calls older than 60 s
            if len(self._starts) < self._per_minute:
                self._starts.append(now)          # take a slot
                return
            await self._sleep(self._starts[0] + 60 - now)   # wait for the oldest to expire
```
A **sliding window**: keep the start times of the last 60 seconds. If there is room, record this call and go. If not, sleep until the **oldest** start is 60 seconds old, then check again. `clock` and `sleep` can be replaced in tests so "wait 60 s" takes no time.

---

# Q38: what was `asyncio.Lock` used for?

The first version of the code was:
```python
self._lock = asyncio.Lock()

async def acquire(self):
    async with self._lock:          # one caller at a time
        while True:
            ...
```
An `asyncio.Lock` is a **door with room for one**. `async with self._lock:` means "wait until nobody is inside, enter, and leave the door open for the next one when I am done". Waiting tasks are served **first come, first served** (that is how `asyncio.Lock` is documented to behave). It works between async tasks of one process only; it is not a thread lock.

The lock was held **while sleeping** (in the limiter's own wait), so waiting callers queued at the door instead of each running its own timer.

# Q39: who calls `lock.acquire()`?

Nobody writes it. **`async with self._lock:` calls it for you.** Python turns the block into roughly:
```python
await self._lock.acquire()      # on entering: wait for a free door, then lock it
try:
    ...the work...
finally:
    self._lock.release()        # on leaving: always, even after return or an error
```
That is why `async with` is the recommended form: you cannot forget the release. The semaphore works the same way (`async with self._semaphore:` calls `acquire()` and `release()`).

There were **two different "acquire" names**:
| Name | What it is | Who calls it |
|---|---|---|
| `RateLimiter.acquire()` | my method: "wait until I am allowed to start a call" | `LimitedClient._start()` |
| `asyncio.Lock.acquire()` | the lock's own method | the `async with self._lock:` line inside my `RateLimiter.acquire()` |

```
LimitedClient.generate
    async with self._semaphore:                  # Semaphore.acquire() (automatic)
        await self._start()
            await self._limiter.acquire()        # my RateLimiter.acquire()
                async with self._lock:           # Lock.acquire() (automatic)
                    ...window check, maybe sleep...
                                                 # Lock.release() (automatic)
        return await self._inner.generate(...)   # the real call
                                                 # Semaphore.release() (automatic)
```
Each running request is its own async task; with 6 requests at once, 6 tasks reach the lock line, one enters, five are suspended there until it is released.

# Q40: if the model handles many calls at a time, why a lock? Is checking `len(starts)` enough?

**You were right.** The lock was not needed for correctness, and it did **not** limit the model's concurrency.

1. **It never limited the model.** The lock was released **before** the real model call (`return await self._inner.generate(...)` comes after `_start()` finished). Four calls could run at the same time. How many run at once is the **semaphore's** job.
2. **The length check is already safe.** asyncio runs one task at a time and switches only at an `await`. These lines have **no `await` between check and write**:
   ```python
   if len(self._starts) < self._per_minute:
       self._starts.append(now)
       return
   ```
   so two tasks cannot both take the last slot. The only `await` is the `sleep`, and after it the loop checks the window again.
3. **What the lock actually added** was behaviour, not correctness: waiters served in arrival order, and fewer wasted wake-ups (without the lock all sleepers wake at the same moment and all but a few go back to sleep). I have **not measured** either effect, and asyncio does not promise an order for timers with the same wake-up time, so the lock was a way to make the order explicit. For a batch of 50 requests it does not matter.

## What I did ("yes simplify")
Removed `self._lock` and the `async with self._lock:` line, un-indented the loop, and put a comment in its place:
```python
async def acquire(self) -> None:
    # No lock needed: asyncio switches tasks only at an `await`, and the check and the
    # append below have none between them, so two tasks cannot take the same last slot.
    # After the sleep the loop checks again, so a woken task never skips the limit.
    while True:
        ...
```
Checked afterwards: the 21 wrapper tests pass (including `test_the_per_minute_limit_makes_the_next_call_wait`), all **162** tests pass, strict mypy and ruff are clean. The explanation file `../explanation/06-llm_wrappers.md` was updated to match.

## Quick check
- Which object limits how many model calls run at once: the lock or the semaphore?
- Why can two tasks not both take the last slot, even without a lock?
- Who calls `Lock.acquire()` when you write `async with lock:`?
- What did the lock add that the length check alone did not give?
