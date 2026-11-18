# Routes, `chat_service`, prompt caching and the small changes

> **Update (Day 7):** the `/chat` system prompt is now a **registry prompt**: the long handbook is `prompts/chat_system/v1.md` and the one-line default is `prompts/chat_basic/v1.md`, chosen by the settings `CHAT_PROMPT_NAME` and `CHAT_PROMPT_VERSION`. `CHAT_SYSTEM_PROMPT`, `CHAT_SYSTEM_PROMPT_FILE` and `chat_service.system_prompt()` no longer exist (it is `chat_service.chat_prompt()` now). The text below describes Day 6.

This file covers what Day 6 changed in files that already existed:
1. `src/ai_service/api/v1/extract.py` (66 lines)
2. `src/ai_service/api/v1/chat.py` (the `POST /chat` function, lines 33 to 139)
3. `src/ai_service/services/chat_service.py` (lines 13 to 48, 254 and 268)
4. `src/ai_service/prompts/chat_system.md` (the cached system prompt)
5. `src/ai_service/main.py`, `core/logging.py` (small additions)

The unchanged parts of `chat.py` and `chat_service.py` (conversation queries, `chat_stream` body) are explained in `notes/day-5/01-chat-and-extract.md`.

---

# 1. `api/v1/extract.py`

## Lines 1 to 17: header
Imports now include `Request` (to read the request id), `DbSession` (see line 34 below), `request_id_of` (reads the id the middleware assigned), `Backend` and `CallContext`. `cast` is used once (line 56).

## Lines 20 to 23: the signature
```python
async def extract_enquiry(body, request, user, llm, session) -> ExtractResponse:
```
FastAPI fills each parameter: `body` from the JSON, `request` the raw request, `user` from the token (`get_current_user`), `llm` the registry, `session` the request's database session. `session` is new in Day 6, and **only so it can be committed** (line 34).

## Lines 31 to 34: giving the database connection back (a bug found by the burst test)
```python
await session.commit()
```
`get_current_user` read the user inside a transaction, which holds a **database connection checked out until the request ends**. The model call below can take seconds. With 25 requests at once, 25 requests held 25 connections, but the pool has 15: ten answered `500` (`QueuePool limit of size 5 overflow 10 reached`) while the model was healthy. `commit()` ends the transaction and **returns the connection to the pool**. The `user` object stays loaded because the session is configured with `expire_on_commit=False`. A test (`test_the_database_connection_is_given_back_before_the_model_is_called`) fails without this line.

Rule to remember: **never hold a database connection across a slow external call.**

## Lines 35 to 41: get the client and label the call
`llm.get(body.backend)` returns the fully wrapped client. `CallContext` carries the request id (from `request_id_of(request)`), the tenant and user as strings, and `feature="extract"`. It travels inside every `LLMRequest`, so the log line and the `llm_calls` row know who the call was for.

## Lines 42 to 44: time and call
`perf_counter()` before and after: `latency_ms` of the **whole** request (repairs included). `extract_service.extract(...)` does the work (`08-extract_service_and_schema.md`).

## Lines 46 to 52: the log line
One `INFO` line: which backend answered, how long, how many attempts. (The per-call details are logged separately by `AccountingClient`.)

## Lines 53 to 65: the response
`ExtractResponse(data=..., meta=ExtractMeta(...))`:
| Line | Meaning |
|---|---|
| 56 | `backend=cast(Backend, result.backend)`: `result.backend` is a plain `str`; `cast` tells the type checker it is one of the three allowed values |
| 57 | `model=result.model`: the model that **answered** |
| 60 | `fallback_used = result.backend != body.backend` |
| 61 to 63 | Tokens from the summed `Usage`; `None` if the provider gave none |

---

# 2. `api/v1/chat.py`: `POST /chat` (lines 33 to 139)

## Lines 20 to 26: imports
`CallContext`, `LLMRequest`, `StreamStart` (new). `LLMError` and `ChatMessage` as before.

## Lines 53 to 66: client, conversation, history
`client = llm.get(body.backend)` (was `provider`). If a `conversation_id` is given: load the conversation (404 if it is not the user's) and the last `CHAT_HISTORY_LIMIT` messages. Unchanged from Day 5 apart from the name.

## Lines 67 to 69: give the connection back
Same fix as `/extract`: `await session.commit()` **after the reads, before the wait for the model**. The session opens a new transaction by itself when `start_turn` needs it (line 114). In `/chat` this matters even more: the wait for the first token has been seen to take 1 to 60 seconds.

## Lines 71 to 77: the message order (this is what makes caching work)
```python
messages = [
    ChatMessage("system", chat_service.system_prompt(settings)),
    *history,
    ChatMessage("user", body.message),
]
```
**Stable part first, changing part last.** Providers cache a **prefix**: the match goes from the first token and stops at the first difference. The system prompt never changes, the history only **grows at the end**, and the new message is last, so each turn shares a long prefix with the previous one. A timestamp or user name at the top would break it.

## Lines 78 to 83: `call_context`
Same as in `/extract` but `feature="chat"`. The request id is read with `getattr(request.state, "request_id", None)` (kept from Day 5; the test `GoneRequest` fake has `state` but no `scope`).

## Lines 85 to 100: wait for the first text, handle the model name
| Line | Meaning |
|---|---|
| 88 | `client.stream(LLMRequest(messages, cache_system=True, context=call_context))`: **`cache_system=True`** asks for the stable system prompt to be cached (Anthropic adds `cache_control`; Gemini and OpenAI do it by themselves) |
| 89 | `served_model = client.model`: the default name |
| 91 | `first = await anext(events)`: the first event. By the time it returns, **all** retries and a possible fallback have already happened (inside the client), because `_prime` reads up to the first text |
| 92 to 94 | The first event is the `StreamStart`: it names the **model that really answers** (it can be the fallback's). Save it in `served_model` and read the next event, the first real one |
| 95 to 97 | `LLMError` (all retries and the fallback failed) or an empty stream: close and answer `502` (the clean error, since nothing was sent or stored yet) |
| 98 to 100 | Anything else, such as the client leaving while we wait (a cancellation): close the upstream call and re-raise |

## Lines 102 to 112: unchanged Day 5 logic
`context` is the dict for the log lines. If the client already left (`request.is_disconnected()`), close the upstream call, store nothing, answer `499` (no orphan question left in the database).

## Lines 114 to 139: store and stream
`start_turn` stores the conversation and the user message and commits (opens its own new transaction). `StreamingResponse(chat_stream(...))`: the one change is **`model=served_model`** (line 129), so the `start` event and the **saved message** name the model that answered, even after a fallback. (Live test: with the hosted URL dead and the fallback on, the saved message said `gemma3:270m`.)

---

# 3. `services/chat_service.py` (the Day 6 additions)

## Lines 13 and 21: imports
`lru_cache` (to read the file once) and `BASE_DIR`, `Settings` from config.

## Lines 34 to 37: `_read_prompt_file`
```python
@lru_cache
def _read_prompt_file(path: str) -> str:
    file = Path(path)
    return (file if file.is_absolute() else BASE_DIR / file).read_text(encoding="utf-8").strip()
```
Reads the prompt file **once** (`@lru_cache` remembers the result per path). A relative path starts at the project folder (`BASE_DIR`). `.strip()` removes the leading and trailing blank lines. **Restart the server after editing the file**, because the text is cached (this bit me during the live test).

## Lines 40 to 48: `system_prompt(settings)`
If `CHAT_SYSTEM_PROMPT_FILE` is set, return the file's text; else return the short `CHAT_SYSTEM_PROMPT`. The docstring states the reason: it is first in every request and never changes, so a long one is read from the provider's cache from the second turn on.

## Line 254: `elif isinstance(pending, Finish)`
Was `else` on Day 5. The event union now has three members; the `isinstance` check lets the type checker know `pending` is a `Finish` there.

## Line 268: `"cache_read_tokens": finish.cache_read_tokens`
The `done` SSE event now carries the cached tokens next to `input_tokens` and `output_tokens`. Real values from the run: turn 1 `0`, turn 2 `2030`.

---

# 4. `prompts/chat_system.md`: the cached system prompt
About 20,000 characters, roughly **4,800 tokens**: the handbook of a fictional institute ("Bright Path Academy"): how to answer, courses and fees, packages, payments, refunds, admission steps, timetables, week-by-week syllabus, rules. Read it as a **realistic long, stable prompt** (a real product would have one like it).

**Why it is that long:** the provider only caches a prefix **above a minimum size**. With a 3.5K-token prompt, `cache_read_tokens` was `0` on every turn. With about 4.8K tokens, turn 2 onward showed about 2,030 cached tokens (about 40% of the prompt) and a turn cost about 30% less. A direct test showed the cache starting around 4K tokens and caching in chunks, and only after repeated identical calls. Caching is best effort; the first call of a run is always cold.

It is switched on by `CHAT_SYSTEM_PROMPT_FILE=src/ai_service/prompts/chat_system.md` in `.env`. A test (`test_the_shipped_system_prompt_is_long_enough_to_be_cached`) checks it stays above 16,000 characters, so nobody shortens it by accident.

---

# 5. Small changes in other files

## `main.py` (lines 19 to 20 and 27 to 28)
```python
from ai_service.db.session import async_session_factory, engine
from ai_service.services.llm_accounting import DbCallRecorder
...
app.state.llm = SettingsLLMRegistry(get_settings(), DbCallRecorder(async_session_factory))
```
The lifespan builds the registry **with a recorder**, so every call made through it is saved to `llm_calls`. `async_session_factory` is the same factory the app already used; the recorder opens its own short sessions from it.

## `core/logging.py` (lines 26 to 39)
The JSON formatter prints only a **fixed list** of extra fields from a log record. Day 6 adds `feature`, `backend`, `model`, `operation`, `status`, `error_type`, `stop_reason`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cost_usd`, `latency_ms`. Without this, the values passed in `extra={...}` by `AccountingClient` would be **silently dropped** from the output.

## `core/exceptions.py`
`ExtractionRefusedError` (see `08-...`).

## `.env.example`
A new "Day 6" block: `CHAT_SYSTEM_PROMPT_FILE`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `LLM_FALLBACK_BACKEND`, the four `LLM_RETRY_*`, `LLM_MAX_CONCURRENCY`, `LLM_REQUESTS_PER_MINUTE`, and a commented example of overriding `LLM_PRICES`. Empty values are safe because of `blank_means_not_set` (`07-...`).

## `pyproject.toml` and `uv.lock`
`anthropic` added (`uv add anthropic`, version 2.8.0 at the time).

## Quick check
- Why must `session.commit()` come before the model call in both routes?
- Why does the prompt order matter for caching: which part is first, which is last?
- What does `StreamStart` give the route that `client.model` does not?
- Why was the `JSONFormatter` list extended, and what happens without it?
- Why is the system prompt about 4,800 tokens?
