# `services/llm_wrappers.py`: limits, retry and fallback

**File:** `src/ai_service/services/llm_wrappers.py` (297 lines, new on Day 6)
**Job:** three layers that wrap any `LLMClient` and are `LLMClient`s themselves, so they **stack** like Express middleware:
```
FallbackClient( RetryingClient( LimitedClient( AccountingClient( adapter ) ) ) , the same for the second backend )
```
- `LimitedClient`: do not send too many calls at once or per minute.
- `RetryingClient`: when a call fails for a temporary reason, wait and try again.
- `FallbackClient`: when a backend still fails, ask the next one.

Because each layer only talks to "an `LLMClient`", each one can be tested alone with a scripted fake and no real waiting (`tests/test_llm_wrappers.py`, 21 tests).

> **Line numbers:** after the `RateLimiter` lock was removed, everything from `LimitedClient` onward moved **down by one line** in the real file. The numbers below that point are one lower than the file.

---

## Lines 1 to 11: docstring
Draws the stack and states the **one big rule for streams** (lines 9 to 10): a retry or a fallback may only happen **before the first text**. After the client has seen words, starting again would show them twice. The two helpers below exist to enforce that rule.

## Lines 13 to 32: imports
`asyncio` (sleep, semaphore, lock), `logging`, `random` (jitter), `time` (monotonic clock), `deque` (a fast queue for the rate limiter), the typing helpers, `dataclass`, `anyio` (the `CancelScope` that shields clean-up), `Settings` (to build the retry policy), and my types.

---

## Lines 37 to 48: `_prime(events)`
```python
buffered = []
async for event in events:
    buffered.append(event)
    if not isinstance(event, StreamStart):
        break
return buffered
```
"Read the stream up to and including the first event that is **not** a `StreamStart`." Every stream begins with a `StreamStart` (no text), then the first real event (a `TextDelta`, or a `Finish`).
- Why this matters: the HTTP call is made when the generator first runs, and a slow or failing provider raises its error **while we wait for that first real event** (a 429, a timeout waiting for the first token). By pulling that far **before returning anything to the caller**, the wrapper can still decide to retry or fall back.
- The events read are **buffered** in a list and replayed afterwards, so nothing is lost.
- `break` out of an `async for` does **not** close an async generator, so the generator stays usable for the rest of the stream.

## Lines 51 to 53: `_close(events)`
```python
with anyio.CancelScope(shield=True):
    await events.aclose()
```
`aclose()` closes the generator, which runs its `finally` and closes the HTTP connection. It is wrapped in a **shielded cancel scope** because this is often called while the task is being cancelled (a client left): without the shield, the cancellation would interrupt the clean-up itself and the upstream call could stay open. This is the same trick as Day 5's `chat_stream` `finally`.

---

## Lines 59 to 85: `RateLimiter` (a sliding window)
Goal: at most `per_minute` calls **start** in any 60 seconds (Gemini's free tier allows 15).
| Line | Meaning |
|---|---|
| 62 to 68 | `per_minute`, plus two **injectable** functions, `clock` and `sleep`, defaulting to the real ones. Tests pass fakes so a test of "wait 60 s" takes no time |
| 72 | `_starts`: a `deque` of the times of recent calls |
| 75 to 77 | The comment explains why **there is no lock**: asyncio switches tasks only at an `await`, and the check and the append have no `await` between them, so two tasks cannot take the same last slot |
| 78 to 79 | `while True:` then `now = self._clock()` |
| 80 to 81 | Drop every start time that is 60 seconds or older (they left the window) |
| 82 to 84 | If fewer than `per_minute` calls are in the window: record this call and return (go ahead) |
| 85 | Otherwise **sleep until the oldest call leaves the window** (`oldest + 60 - now`), then loop and check again |

**History:** the first version had an `asyncio.Lock` around this loop, "to keep waiters in order". It was removed (Day 6 follow-up) because it was not needed for correctness: after the `sleep` every task checks the window again, so a woken task can never skip the limit. The only things the lock added were first-come-first-served order and fewer wasted wake-ups, which do not matter for a batch of 50 requests. The lock was never limiting the model's concurrency either (it was released before the real call); that is the semaphore's job in `LimitedClient`.

## Lines 87 to 123: `LimitedClient`
One per backend. It limits **how many calls run at once** (a semaphore) and **how many start per minute** (the `RateLimiter`).
| Line | Meaning |
|---|---|
| 90 | `max_concurrency` and `per_minute` are keyword-only; `per_minute=0` means no per-minute limit |
| 92 | `asyncio.Semaphore(n)`: at most n holders at a time |
| 93 | A `RateLimiter` only if `per_minute > 0`, else `None` |
| 94 to 95 | Copy `backend` and `model` from the wrapped client (the protocol needs them; see `01-llm_types.md`) |
| 97 to 99 | `_start()`: wait for the rate limiter if there is one |
| 101 to 104 | `generate`: `async with self._semaphore` (wait for a free slot), `_start()`, call the inner client. The slot is released automatically when the block ends, **even on an error or a cancellation** |
| 106 to 113 | `generate_structured`: identical |
| 115 to 123 | `stream`: the semaphore is held for the **whole stream** (line 116). Inside: wait the limiter, open the inner stream, `yield` each event, and in `finally` close it with `_close` |

Why the limit sits **inside** the retry layer (in the stack order above): every retry attempt must also pass the limiter, otherwise a burst of retries could break the per-minute limit again.

---

## Lines 129 to 143: `RetryPolicy`
A frozen dataclass of the four numbers (`attempts=3` tries in total including the first, `base_delay=1.0`, `max_delay=20.0`, `total_seconds=90.0`). `from_settings` (136 to 143) builds it from the `LLM_RETRY_*` settings. The return annotation `RetryPolicy` needs no quotes on Python 3.14.

## Lines 146 to 162: `RetryingClient.__init__`
Stores the wrapped client and the policy. Three **injectable** parameters (`sleep`, `jitter`, `clock`) default to the real `asyncio.sleep`, `random.random` and `time.monotonic`. Tests inject a fake clock and a fixed jitter (for example `1.0`) so the waits are exact numbers. Note `jitter` returns 0 up to (not including) 1.

## Lines 164 to 183: `_delay_or_raise(exc, attempt, started)`
Decides: wait this long, **or** give up. It returns the delay or re-raises `exc`.
| Line | Meaning |
|---|---|
| 167 to 168 | **Give up at once** if the error is not retryable, or this was the last allowed attempt. `raise exc` re-raises it (the caller sees the real error) |
| 169 | `ceiling = min(max_delay, base_delay * 2**(attempt-1))`: **exponential backoff**: 1 s, 2 s, 4 s, 8 s ... capped at `max_delay`. `float(2 ** ...)` turns an `Any` from the power into a float for strict mypy |
| 170 | `delay = jitter() * ceiling`: **full jitter**: a random value between 0 and the ceiling, so many clients do not retry at the same moment |
| 171 to 172 | If the provider said how long to wait (`retry_after`), wait **at least that long** (`max`). Live result: Gemini's "retry in 12.1 s" produced waits of about 12 s |
| 173 to 174 | **Time budget**: if time already spent plus this wait would pass `total_seconds`, give up now instead of keeping a request waiting for minutes |
| 175 to 182 | Log a warning with the attempt number, the backend, the error kind and the wait |
| 183 | Return the delay |

## Lines 185 to 194: `_call` (retry loop for non-streaming calls)
```python
async def _call[T](self, call):
    started = self._clock()
    attempt = 0
    while True:
        attempt += 1
        try:
            return await call()
        except LLMError as exc:
            delay = self._delay_or_raise(exc, attempt, started)
        await self._sleep(delay)
```
- `[T]` is the Python 3.12+ generic syntax: it returns whatever `call` returns.
- `call` is a **function with no arguments** (a lambda), so the same loop retries `generate` and `generate_structured`.
- On success it returns. On an `LLMError`, `_delay_or_raise` either raises (then the loop ends with that error) or returns a delay; the `sleep` happens **outside** the `except`, then the loop runs again. Only `LLMError` is caught: any other exception (a bug) is not hidden.

## Lines 196 to 204
`generate` and `generate_structured` are one-liners: wrap the inner call in a lambda and pass it to `_call`.

## Lines 206 to 229: `RetryingClient.stream`
The same idea for streams, with the "only before the first text" rule:
| Line | Meaning |
|---|---|
| 207 to 210 | Start the clock, count the attempt |
| 211 | A **new** inner stream for each attempt |
| 213 | `_prime(events)`: read up to the first real event |
| 214 to 216 | The prime failed with an `LLMError`: close this attempt's stream and ask `_delay_or_raise` (raises if no more tries) |
| 217 to 219 | Any other exception (including `CancelledError`, a client leaving while we waited): close the stream and **re-raise**, do not retry |
| 220 to 221 | `else: break`: the prime worked; leave the loop |
| 222 | After a retryable failure: sleep, then loop for another attempt |
| 223 to 229 | **After** the loop (no more retries from here): replay the buffered events, then pass on the rest of the stream, and close in `finally`. An error from now on is **not retried**; it goes straight to the caller (the route turns it into an SSE `error` event) |

## Lines 235 to 255: `FallbackClient` setup and `_next_or_raise`
| Line | Meaning |
|---|---|
| 242 to 245 | A list of clients, **in order**. It copies `backend` and `model` from the first (the primary) |
| 247 to 249 | `_next_or_raise`: if the error is **not** `fallback_ok`, or this was the **last** client, re-raise it. A wrong key (`AuthError`) fails here at once instead of hiding a config bug behind a fallback |
| 250 to 255 | Otherwise log `llm fallback: hosted failed (RateLimitedError), trying local` and return normally (the loop moves to the next client) |

## Lines 257 to 275: `generate` and `generate_structured`
`for index, client in enumerate(self._clients)`: try each in turn; `return await client.generate(...)` ends the function on the first success; on `LLMError` call `_next_or_raise` (raise, or move on). Line 263 / 275, `raise AssertionError(...)`, can never run (the last client re-raises); it satisfies the type checker and documents the claim.

## Lines 277 to 296: `stream`
Same loop with `_prime`: if the primary fails **before its first text**, close it and try the next client (`continue`). Otherwise stream from the one that worked, then `return`. The response says which client answered: the buffered `StreamStart` carries that client's `model` and `backend`, which the chat route reads to name the model in the `start` event and in the saved message.

---

## What was tested (and live-proven)
- Unit: waits 1 s, 2 s; jitter; `retry_after` obeyed; time budget; stream retry only before text; fallback rules; concurrency peak equals the limit; the sliding window waits 60 s (all without real waiting).
- Live: with the hosted URL on a dead port and `LLM_FALLBACK_BACKEND=local`, `/extract` and `/chat` logged 3 tries and then answered from the local model. A burst of 25 requests at once against the real free tier ended with 25 answers after reading Gemini's "retry in 12 s".

## Quick check
- Why does `_prime` read up to the first non-`StreamStart` event?
- What does "full jitter" mean, and what does `retry_after` change?
- Why is the semaphore held for the whole stream in `LimitedClient.stream`?
- Why does `FallbackClient` not fall back on an `AuthError`?
- Why is `_close` wrapped in a shielded cancel scope?
