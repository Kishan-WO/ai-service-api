# Q29. What is `events`? (in the chat streaming code)

> **Update (Day 6):** This describes the **Day 5** code. On Day 6 `stream_chat` became `stream(request)`, a stream now starts with a `StreamStart` event (which model answers), and `Finish` carries `usage` (with `input_tokens`, `output_tokens` and `cache_read_tokens` as read-only properties). The route skips the `StreamStart` before handing `first` to `chat_stream`. See `../../day-6/explanation/01-llm_types.md` and `../../day-6/explanation/09-routes_chat_service_and_small_changes.md`.

`events` is an **async generator of `StreamEvent` objects** produced by the LLM provider: the model's answer arriving piece by piece.
```python
events = provider.stream_chat(messages)
```
`stream_chat` is an `async def` with `yield`, so calling it runs nothing yet. Nothing is sent to the LLM until you pull the first item with `anext(events)`.

## What comes out
```python
if isinstance(pending, TextDelta):   # a piece of text
    ...
else:
    finish = pending                 # final Finish object
```
- **`TextDelta`**: a small chunk (`.text`), many of them.
- **`Finish`**: once at the end, with `stop_reason`, `input_tokens`, `output_tokens`.

```
TextDelta("Hel") -> TextDelta("lo!") -> ... -> Finish(stop_reason="end_turn", ...)
```
Then `anext(events)` raises `StopAsyncIteration`.

## How it's consumed
1. **Route**: `first = await anext(events)`. If the provider fails here, a clean 502 can still be returned since nothing was sent or saved.
2. **`chat_stream`**: handles `first`, then loops `pending = await anext(events)` until `StopAsyncIteration`. `first` is passed separately because it was already pulled.

## Why it must be closed
```python
await events.aclose()
```
An open generator holds a live HTTP connection to the provider. `aclose()` stops generation (so you stop paying for tokens). Called on every exit path.

| | |
|---|---|
| What | async generator yielding `TextDelta` and one `Finish` |
| Created by | `provider.stream_chat(messages)` |
| Pulled with | `await anext(events)` or `async for` |
| Holds | a live connection to the provider |
| Must be | closed with `await events.aclose()` |
