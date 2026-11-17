# Q36. What is the purpose of `_prime`? (second answer: how the retry and fallback layers use it)

**What I asked (pasted code):**
```python
async def _prime(events: AsyncGenerator[StreamEvent]) -> list[StreamEvent]:
    """Read up to and including the first event that is not a StreamStart.
    ...
    buffered: list[StreamEvent] = []
    async for event in events:
        buffered.append(event)
        if not isinstance(event, StreamStart):
            break
    return buffered
```
**File:** `src/ai_service/services/llm_wrappers.py` (lines 37 to 48)

---

## The short answer
`_prime` reads the **start** of a stream and keeps what it read, so that a failure at the start is discovered **while a retry or a fallback is still possible**. Once the user has seen any text, starting again would show it twice, so the retry window closes at the first word.

## The problem: a generator is lazy
A stream is an **async generator**. Creating it runs nothing:
```python
events = client.stream(request)    # no HTTP call yet, no error possible yet
```
The HTTP call, and so any error, happens only when something **starts reading** the generator. A failing provider usually fails there: a 429, or a timeout while waiting for the first token.

If the retry layer simply returned the generator to the caller, the error would appear later, **inside the caller's loop**, after the caller may already have sent text to a user. At that point it is too late to retry.

## What `_prime` does, line by line
| Line | Meaning |
|---|---|
| `buffered = []` | a list to hold the events read so far |
| `async for event in events:` | start reading the stream. **This is the moment the HTTP call happens**, and any provider error is raised **here** |
| `buffered.append(event)` | keep every event; none is thrown away |
| `if not isinstance(event, StreamStart): break` | every stream begins with a `StreamStart` (which model answers, no text). Keep reading until the first **real** event, normally the first `TextDelta`, then stop |
| `return buffered` | give back what was read |

`break` out of an `async for` does **not** close the generator, so the stream is still alive and the callers keep reading it afterwards.

## How the callers use it
In `RetryingClient.stream` (simplified):
```python
while True:
    events = self._inner.stream(request)
    try:
        buffered = await _prime(events)          # may raise: still safe to retry
    except LLMError as exc:
        await _close(events)
        delay = self._delay_or_raise(exc, ...)   # retry later, or give up
        await self._sleep(delay)
        continue
    break
# from here no retry any more:
for event in buffered:       # replay what _prime read
    yield event
async for event in events:   # then the rest of the stream
    yield event
```
`FallbackClient.stream` does the same, but on failure it moves to the **next client** instead of waiting.

The events `_prime` read are not lost: they sit in `buffered` and are replayed first.

## Why it stops at "the first non-start event"
- **Reading less** (only the `StreamStart`) would not wait for the real first token. A provider can connect and then time out before sending any text; that error would come after the caller had started streaming, too late to retry.
- **Reading more** would hold back text the user is already waiting for, which defeats streaming.

## Real effects you can see
- `/chat` answers a clean **502** for a dead provider (nothing was sent yet), instead of a half-started stream.
- With the hosted URL on a dead port and the fallback on, `/chat` logged 3 failed tries, then `llm fallback: hosted failed, trying local`, and streamed from `gemma3:270m`. The `start` event named `gemma3:270m` because the buffered `StreamStart` came from the fallback client.
- Tests: `test_a_stream_is_retried_while_no_text_has_been_sent` (a 429 before any text, then a good stream: one `StreamStart`, the text once, both attempts closed) and `test_a_stream_is_not_retried_after_text_was_sent`.

## Quick check
- Why does an error in a stream appear only when you start reading it?
- Why is the first `TextDelta` the point of no return?
- What would happen to the text `_prime` reads if it were not stored in `buffered`?
