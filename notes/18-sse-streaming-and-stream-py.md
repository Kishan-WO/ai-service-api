# Server-Sent Events and `api/v1/stream.py`

Question: explain `stream.py` line by line (everything except the route first), why Swagger shows "loading" for a stream, and what a real example with an AI model looks like.

## 1. What SSE is
**Server-Sent Events** is a simple way for a server to push messages to a client over **one long-lived HTTP response**. The server keeps the connection open and writes small text messages as they become ready.

| | SSE | WebSocket |
|---|---|---|
| Direction | Server → client only | Both ways |
| Built on | Plain HTTP | A separate protocol |
| Format | Plain text | Anything |
| Good for | Streaming an AI answer, progress, notifications | Chat rooms, games |

An SSE message is text, ending with a blank line:
```
event: token
data: {"index": 0, "text": "Streaming"}

event: token
data: {"index": 1, "text": "lets"}

event: done
data: {"words": 40}

```
The response header is `Content-Type: text/event-stream`.

## 2. `stream.py`, lines 1-58 (everything except the route)

### The setup (lines 1-22)
```python
logger = logging.getLogger("ai_service.stream")
router = APIRouter(prefix="/stream", tags=["stream"])
DEMO_TEXT = ("Streaming lets a client show an answer while it is still being written. ...")
```
- `logger`: a named logger; the disconnect messages go here.
- `router`: all routes in this file start with `/stream`; `tags` groups them in Swagger.
- `DEMO_TEXT`: the paragraph that will be streamed (the fake "LLM answer").

### The Protocol (lines 25-26)
```python
class DisconnectCheck(Protocol):
    async def is_disconnected(self) -> bool: ...
```
A `Protocol` describes a shape: "anything with an async `is_disconnected()` method". The real `Request` object has it, and so does the small fake used in tests. This lets `word_stream` be tested without a real connection.

### Formatting one event (lines 29-31)
```python
def sse_event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
```
Builds one SSE message: an `event:` line, a `data:` line holding JSON, and the **blank line** (`\n\n`) that tells the client the message is complete.

### The generator (lines 34-58)
```python
async def word_stream(request, text, delay_seconds, log_context=None) -> AsyncIterator[str]:
    extra = log_context or {}
    words = text.split()
    sent = 0
    try:
        for index, word in enumerate(words):
            if await request.is_disconnected():
                logger.info("SSE client disconnected after %d of %d words", sent, len(words), extra=extra)
                return
            yield sse_event("token", {"index": index, "text": word})
            sent += 1
            await asyncio.sleep(delay_seconds)
        yield sse_event("done", {"words": sent})
    except asyncio.CancelledError:
        logger.info("SSE stream cancelled after %d of %d words", sent, len(words), extra=extra)
        raise
```
| Line | What it does |
|---|---|
| `async def ... -> AsyncIterator[str]` with `yield` | An **async generator**: produces values over time (see `day-2/learning/11.async-generators.md`) |
| `words = text.split()` | Split the paragraph into words |
| `for index, word in enumerate(words)` | Loop with a counter |
| `if await request.is_disconnected()` | Has the client gone? If so, log it and stop |
| `yield sse_event("token", ...)` | Send one word now |
| `await asyncio.sleep(delay_seconds)` | Pause (simulates the model thinking). **`await`**, so other requests keep running |
| `yield sse_event("done", ...)` | A final message: the stream is complete |
| `except asyncio.CancelledError` | If the server **cancels** the generator while it is waiting (the client hung up), log it and `raise` again so the cancellation still completes |
| `extra=extra` | Adds request id, tenant id and user id to the JSON log line |

Why two ways to detect a hang-up: the `is_disconnected()` check works while the generator is running; a hang-up during `sleep` arrives as cancellation. I saw the second one against the real server: "SSE stream cancelled after 3 of 40 words".

## 3. The route (lines 61-77)
```python
@router.get("/demo")
async def stream_demo(request: Request, user: CurrentUser, delay_ms: Annotated[int, Query(ge=0, le=1000)] = 50):
    context = {"request_id": ..., "tenant_id": str(user.tenant_id), "user_id": str(user.id)}
    return StreamingResponse(
        word_stream(request, DEMO_TEXT, delay_ms / 1000, context),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```
| Part | Meaning |
|---|---|
| `user: CurrentUser` | Login required (see `10-dependencies-deps-walkthrough.md`) |
| `delay_ms` (0-1000, default 50) | Query parameter for the pause between words; tests use 0 |
| `StreamingResponse(generator, ...)` | Sends each value the generator yields **as soon as it is yielded**, without waiting for the end |
| `media_type="text/event-stream"` | Tells the client this is SSE |
| `Cache-Control: no-cache` | Proxies must not store or hold the stream |
| `X-Accel-Buffering: no` | Tells nginx not to buffer it |
| `context` | Ids attached to the log lines |

The route does not run the generator; it **hands it to** `StreamingResponse`, which pulls from it.

## 4. Why Swagger shows "loading" and the text only at the end
Swagger UI is a normal fetch-and-show tool: it **waits for the response to finish** and then prints it. It cannot display a stream live. The server is streaming correctly: I measured the real endpoint sending 40 words over about 0.8 s, the first after 7 ms.

Ways to see it live:
```bash
curl -N -H "Authorization: Bearer <token>" "http://localhost:8000/api/v1/stream/demo?delay_ms=200"
```
`-N` turns off curl's buffering. A browser can read it with `fetch()` and a stream reader (the header needs a token, so `EventSource` cannot send it directly).

## 5. A real example with an AI model
The idea is the same: the generator yields what the **model** sends instead of looping over words. This runs against a local model through the OpenAI-compatible endpoint, and works the same with a hosted provider (change `base_url`, `api_key`, `model`):

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

async def llm_stream(prompt: str) -> AsyncIterator[str]:
    index = 0
    stream = await client.chat.completions.create(
        model="gemma3:270m", stream=True, max_tokens=60, temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    async for chunk in stream:
        text = chunk.choices[0].delta.content if chunk.choices else None
        if text:
            yield sse_event("token", {"index": index, "text": text})
            index += 1
    yield sse_event("done", {"tokens": index})
```
Real run with the local `gemma3:270m` model:
```
events: 13 | first after 3747 ms        (the first call includes loading the model)
text: The Indian flag is a vibrant shade of **red**.
```
In the route the only change is `StreamingResponse(llm_stream(prompt), media_type="text/event-stream")`. Additions a production version needs: check `request.is_disconnected()` between chunks, set a timeout, handle provider errors with an `event: error` message, and keep the API key in `.env`.

## 6. Client side (browser)
```javascript
const res = await fetch("/api/v1/stream/demo", { headers: { Authorization: `Bearer ${token}` } });
const reader = res.body.getReader();
const decoder = new TextDecoder();
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  console.log(decoder.decode(value));   // "event: token\ndata: {...}\n\n"
}
```

## Common mistakes
| Mistake | What happens |
|---|---|
| Missing the blank line after an event | The client never sees the message as complete |
| Using `time.sleep` in the generator | Freezes the whole server |
| Not catching `CancelledError`, or swallowing it | Cleanup is skipped, or the task cannot stop |
| A proxy that buffers the response | The client gets everything at the end |
| Testing the stream in Swagger | Shows "loading" until the end; use curl `-N` |
| Forgetting `media_type="text/event-stream"` | Clients may not treat it as a stream |

## Quick check
- What does an SSE message look like, and what ends it?
- What does `StreamingResponse` do with a generator?
- Why does `word_stream` handle both `is_disconnected()` and `CancelledError`?
- Why does Swagger not show the stream live?
- What changes in the generator when the words come from a real model?
