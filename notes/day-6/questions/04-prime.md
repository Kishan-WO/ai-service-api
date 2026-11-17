# Q33. Meaning of `_prime`

> **Update (Day 6):** The code below is from the moment the question was asked. Since then `stream_chat` was renamed `stream` (it now takes an `LLMRequest`). `_prime` itself is unchanged. A second, longer answer to the same question, with how the retry and fallback layers call it, is in [05-prime-and-stream-retry.md](05-prime-and-stream-retry.md).

```python
async def _prime(events: AsyncGenerator[StreamEvent]) -> list[StreamEvent]:
    buffered: list[StreamEvent] = []
    async for event in events:
        buffered.append(event)
        if not isinstance(event, StreamStart):
            break
    return buffered
```

`_prime` **pulls the first few events and buffers them**, so any early failure happens *now*, while you can still retry or fall back ("prime the pump").

## What it does
Reads events and stops after the first one that is **not** a `StreamStart`. Result examples:
```
[StreamStart, TextDelta("Hel")]
[TextDelta("Hel")]
[StreamStart, Finish(...)]     # empty answer
```
`StreamStart` is metadata with no text; the first non-`StreamStart` event proves the model is answering.

## Why
- **Before any text:** rate limit (429), timeout, overload: safe to retry/fail over since the client got nothing.
- **Mid-stream:** can't restart cleanly.

Any `LLMError` raised before the first real event propagates out of `_prime`:
```python
try:
    buffered = await _prime(provider.stream_chat(messages))
except LLMError as exc:
    if exc.fallback_ok:
        ...  # next provider
```
Same idea as `first = await anext(events)`, skipping the `StreamStart` marker.

## Buffered events must be replayed
```python
async def replay(buffered, events):
    for event in buffered:
        yield event
    async for event in events:
        yield event
```

## Notes
- Returns a plain `list`, not a generator.
- Empty stream → returns whatever was buffered (possibly `[]`); caller must handle it.
- It doesn't close the generator; on error the caller should `await events.aclose()`.
