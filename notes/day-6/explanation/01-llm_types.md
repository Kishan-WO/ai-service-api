# `services/llm_types.py`: the shapes everything else speaks

**File:** `src/ai_service/services/llm_types.py` (212 lines, new on Day 6)
**Why it exists:** Day 5 had one provider class and its types mixed in one file. Day 6 needs many providers and many wrappers (retry, fallback, accounting). They can only stack if they all speak **the same small set of types**. This file is that set. It imports **no SDK** (no `openai`, no `anthropic`), so the routes and services never depend on a vendor.

Express comparison: this is like a shared `types.ts` plus an `errors.ts`, with one interface (`LLMClient`) that every layer implements.

---

## Lines 1 to 5: the module docstring
```python
"""The shapes every language-model adapter speaks: requests, responses, usage and errors.
...
```
Says what the file is for and states the rule: **nothing here imports a provider SDK**. That rule is what makes a provider swappable.

## Lines 7 to 9: imports
| Line | Code | Meaning |
|---|---|---|
| 7 | `from collections.abc import AsyncGenerator` | The type of `stream()`: an async generator that yields events |
| 8 | `from dataclasses import dataclass, field` | `dataclass` writes `__init__`, `__eq__` and `__repr__` for plain data classes; `field` lets a default be built by a function (line 109) |
| 9 | `from typing import Any, Literal, Protocol` | `Literal` for fixed string choices; `Protocol` for the interface (structural typing, like a TypeScript `interface`); `Any` for the schema dict |

## Lines 11 and 12: the two fixed-choice types
```python
Backend = Literal["hosted", "local", "anthropic"]
Role = Literal["system", "user", "assistant"]
```
- `Backend` is the name a request chooses (`{"backend": "hosted"}`): hosted Gemini, local Ollama, or Anthropic. FastAPI uses this type in the request schema, so Swagger shows a dropdown and any other value is a 422.
- `Role` is who wrote a message. Same three roles as Day 5 `1.messages-api.md`.

## Lines 14 to 18: the shared stop-reason vocabulary
```python
STOP = "stop"
LENGTH = "length"
CONTENT_FILTER = "content_filter"
REFUSAL_REASONS = frozenset({CONTENT_FILTER})
```
Each provider names the end of an answer differently (OpenAI `stop`, Anthropic `end_turn`, Gemini `STOP`/`SAFETY`). The adapters translate them into **three words** so the rest of the code can write `if response.stop_reason == LENGTH`.
- `LENGTH` means "cut off by `max_tokens`". `/extract` must not retry it, because it would be cut off again.
- `CONTENT_FILTER` means a refusal. `REFUSAL_REASONS` is a `frozenset` (an immutable set) so `extract_service` can write `stop_reason in REFUSAL_REASONS`. It has one member now and can grow without changing callers.

## Lines 21 to 82: the error family
All my errors inherit from one base, so the retry code can write `except LLMError` once.

### Lines 24 to 40: `LLMError`
| Line | Meaning |
|---|---|
| 24 | Base class for every provider failure |
| 31 | `retryable = False`: a **class attribute** (not an instance field). Subclasses override it. Meaning: "trying the same call again can work" |
| 32 | `fallback_ok = False`: "another provider may succeed even if waiting here will not" |
| 34 | The constructor takes a message and an optional **keyword-only** `retry_after` (the `*` forces the name) |
| 35 | `super().__init__(message)` keeps the normal `Exception` behaviour (`str(exc)` is the message) |
| 36 | `self.retry_after`: seconds the provider told us to wait. `None` if it did not say |
| 38 to 40 | `kind` property returns the class name (`"RateLimitedError"`). It is what the log line and the `llm_calls.error_type` column store, so a bad run can be grouped by kind |

Why class attributes instead of a status code? The retry layer should not know about HTTP. The **adapter** decides what an HTTP 429 means (it raises `RateLimitedError`); every layer above only asks `exc.retryable`.

### Lines 43 to 82: the subclasses
| Class | Source | `retryable` | `fallback_ok` | Why |
|---|---|---|---|---|
| `RateLimitedError` (43) | 429 | yes | yes | A minute later it works; another provider has its own limit |
| `OverloadedError` (50) | 5xx, 529, 408 | yes | yes | The provider is busy or broken right now |
| `LLMTimeoutError` (57) | no answer in time | yes | yes | The next try may be faster |
| `LLMConnectionError` (62) | cannot connect | yes | yes | The network blip passes; another provider is another route |
| `QuotaExhaustedError` (67) | daily limit, no money | **no** | yes | Waiting a minute does nothing, but another provider has its own quota (only `fallback_ok = True` is set) |
| `ContextTooLongError` (73) | input too big | no | no | The same input fails again, and another provider with a smaller window fails too |
| `AuthError` (77) | 401, 403 | no | no | A wrong key fails everywhere it is used; a fallback would hide a config bug |
| `BadRequestError` (81) | 400, 404 | no | no | The same request fails the same way |

A class with only a docstring (73 to 82) needs no body: both flags inherit `False` from `LLMError`.

## Lines 85 to 109: the request side
### Lines 88 to 91: `ChatMessage`
```python
@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str
```
`frozen=True` makes the object **immutable**: nobody can change a message after it is created, so a wrapper that retries sends exactly what the first try sent. Same type as Day 5.

### Lines 94 to 101: `CallContext`
Who and what a call is for: `request_id`, `tenant_id`, `user_id`, `feature` (`"chat"`, `"extract"`). It travels inside the request (not in a global variable) down to `AccountingClient`, which writes it into the log line and the `llm_calls` row. All default to `None` / `"unknown"` so a script or a test can make a request without a user.

### Lines 104 to 109: `LLMRequest`
| Line | Field | Meaning |
|---|---|---|
| 106 | `messages` | The conversation to send |
| 107 | `max_tokens` | Cap on the reply. `None` means "use the adapter's default" (`LLM_MAX_OUTPUT_TOKENS`). `/extract` sets 400 |
| 108 | `cache_system` | A hint: "my system prompt never changes, cache it if you can". Anthropic reads it (adds `cache_control`); OpenAI-style providers ignore it because they cache a long prefix automatically |
| 109 | `context` | `field(default_factory=CallContext)`: a new `CallContext()` for each request. You cannot write `= CallContext()` directly for a mutable-looking default in a dataclass; `default_factory` is the safe form |

## Lines 112 to 136: `Usage`
The most important data class for cost.
```python
input_tokens: int = 0       # NEW input only
output_tokens: int = 0
cache_read_tokens: int = 0  # input served from the provider's cache
cache_write_tokens: int = 0 # input written to the cache (Anthropic charges extra)
```
- The docstring (116 to 117) states the trap: OpenAI-style `prompt_tokens` **includes** the cached part; Anthropic's `input_tokens` does **not**. Each adapter converts, so `input_tokens` here always means "new, uncached input". If this were not normalised, one provider's cost would be counted twice.
- `prompt_tokens` (125 to 128), a read-only property: everything that was sent, `input + cache_read + cache_write`. It is what the `done` event and the `messages.input_tokens` column show, so Day 5 numbers stay comparable.
- `__add__` (130 to 136) lets code write `usage_a + usage_b`. `extract_service` uses it to add up the tokens of all repair attempts. The return annotation `Usage` has no quotes because Python 3.14 evaluates annotations lazily.

## Lines 139 to 145: `LLMResponse`
What `generate` and `generate_structured` return.
- `text`, `stop_reason` (already in the shared vocabulary).
- `usage: Usage | None`: **`None` means "the provider did not say"**, which is not the same as 0 tokens. A cancelled stream or a server without a usage block gives `None`, and the cost is then `None`, never a made-up 0.
- `model`, `backend`: the model that **really answered**. With a fallback these differ from what the request asked for, and `/extract` reports them in `meta`.

## Lines 148 to 183: the stream events
A stream is a sequence of three kinds of event:
| Class | Line | Meaning |
|---|---|---|
| `StreamStart(model, backend)` | 149 | First event: which model is answering. No text. It exists so the route can know the **real** model after a fallback, before sending its own `start` event |
| `TextDelta(text)` | 157 | A piece of the answer (same as Day 5) |
| `Finish(stop_reason, usage)` | 164 | Last event: why it ended and the token counts |

`Finish` has three read-only properties (170 to 180): `input_tokens` (= `usage.prompt_tokens`), `output_tokens`, `cache_read_tokens`, each `None` when `usage` is `None`. They exist so older code that wrote `finish.input_tokens` (the Day 5 chat service) keeps working unchanged.

Line 183: `StreamEvent = StreamStart | TextDelta | Finish` is a **union type**: anything a stream can yield. `isinstance` checks narrow it.

## Lines 186 to 207: the `LLMClient` protocol
```python
class LLMClient(Protocol):
    backend: str
    model: str
    async def generate(...) -> LLMResponse: ...
    def stream(...) -> AsyncGenerator[StreamEvent]: ...
    async def generate_structured(...) -> LLMResponse: ...
```
- A `Protocol` is **structural typing**: any class that has these attributes and methods *is* an `LLMClient`, with no `extends`. The adapters, every wrapper and the test fakes all qualify just by having the right shape.
- `backend` and `model` (189, 190) are plain attributes: wrappers copy them from the client they wrap, so `client.model` is always available for logging.
- `generate` (192): one complete answer.
- `stream` (196) is a **normal `def`, not `async def`**, because it returns an async generator (an object you iterate with `async for`). The docstring promises the order: one `StreamStart`, many `TextDelta`, one `Finish`, and that closing the generator closes the upstream call.
- `generate_structured` (203): the `*,` makes `schema_name` and `schema` keyword-only. The reply `text` is JSON; **validating it is the caller's job** (the adapter only asks the model to follow the schema).
- The `...` bodies are placeholders (see the `pass` versus `...` note in `../../day-5/questions/09-my-questions-while-reading-the-code.md`).

## Lines 210 to 211: `LLMRegistry`
```python
class LLMRegistry(Protocol):
    def get(self, backend: Backend) -> LLMClient: ...
```
What a route needs to find a client by backend name. `SettingsLLMRegistry` (in `llm.py`) and the test `FakeRegistry` both fit it.

---

## How it connects
- Adapters (`llm_openai.py`, `llm_anthropic.py`) **return** these types.
- Wrappers (`llm_wrappers.py`, `llm_accounting.py`) **take and return** these types, which is why they stack.
- Routes and services only import from here (through `llm.py`, which re-exports it).
- Tests: `tests/fakes.py` builds a fake with exactly this shape.

## Quick check
- Why are `retryable` and `fallback_ok` two flags and not one?
- Why does `Usage.input_tokens` mean "new input only"?
- What is the difference between `usage=None` and `Usage()`?
- Why is `stream` a normal `def` while `generate` is `async def`?
