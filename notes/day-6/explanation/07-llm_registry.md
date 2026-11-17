# `services/llm.py`: the registry that builds the whole stack from settings

**File:** `src/ai_service/services/llm.py` (176 lines; on Day 5 it held the provider class, on Day 6 it only **assembles** things)
**Job:** given a backend name (`"hosted"`, `"local"`, `"anthropic"`) return the right `LLMClient`, already wrapped in every layer. Routes call `llm.get(body.backend)` and never see an SDK, a key, a retry or a limit.

```
registry.get("hosted")  ->  Fallback( Retrying( Limited( Accounting( OpenAICompatProvider ) ) ) , the same for LLM_FALLBACK_BACKEND )
```

---

## Lines 1 to 11: docstring
Draws the stack above and says why the file also **re-exports** the types (lines 61 to 91): so older code can still write `from ai_service.services.llm import ChatMessage, LLMError, ...`, one import place, while the real definitions live in `llm_types.py`.

## Lines 13 to 59: imports
| Line | Import | Why |
|---|---|---|
| 15 | `httpx2` | the HTTP library of both SDKs; needed for `httpx2.Timeout` (line 137) |
| 16, 17 | `AsyncAnthropic`, `AsyncOpenAI` | the two SDK clients the registry constructs. This is the **only** place that creates SDK clients |
| 19 to 20 | `Settings`, `LLMNotConfiguredError` | the settings object and the 503 error |
| 21 to 23 | `AccountingClient`, `CallRecorder`, the two providers | the pieces to assemble |
| 24 to 57 | types and wrappers | `FallbackClient`, `LimitedClient`, `RetryingClient`, `RetryPolicy` |

## Lines 61 to 91: `__all__`
A list of names that are **public** from this module. Without it, linters would say "imported but unused" for the re-exported names. It also documents the module's public surface.

---

## Lines 94 to 102: `SettingsLLMRegistry.__init__`
| Line | Meaning |
|---|---|
| 97 | Takes the `Settings` and an optional `recorder` (what saves `llm_calls` rows). `main.py` passes the real one; tests pass none |
| 100 | `_stacks`: one fully wrapped client **per backend**. Comment: "the limits are shared", because the semaphore and the per-minute window must be **one** object per backend, however many requests use it |
| 101 | `_routes`: what `get()` returns per backend. It differs from `_stacks` only when a fallback is configured |
| 102 | `_sdk_clients`: every SDK client created, kept only so `aclose()` can close them at shutdown |

## Lines 104 to 107: `get`
A **cache**: build once on first use, then return the same object. Nothing is built at start-up, so a service without a key still starts; only a call to that backend fails (with a 503). This is the Day 5 decision 17, kept.

## Lines 109 to 118: `_route` (adds the fallback)
| Line | Meaning |
|---|---|
| 110 | The primary stack. If the primary backend is **not configured** this raises `LLMNotConfiguredError` here, which is right: the request asked for it |
| 111 | `LLM_FALLBACK_BACKEND`: `None`, or the name of a second backend |
| 112 to 113 | No fallback, or the fallback is the same backend: return the primary alone (a backend must not be its own fallback) |
| 114 to 115 | `FallbackClient([primary, self._stack(second)])`: build the second stack and combine |
| 116 to 118 | If the **fallback** is not configured (no key), log a warning and run **without** it. A missing optional fallback must not break the primary |

## Lines 120 to 133: `_stack` (the layers, inside out)
```python
client = AccountingClient(self._adapter(backend), prices=s.LLM_PRICES, recorder=self._recorder)
client = LimitedClient(client, max_concurrency=..., per_minute=...)
self._stacks[backend] = RetryingClient(client, RetryPolicy.from_settings(s))
```
Read it **from the inside**: first the adapter (the real provider call), then accounting around it (one row per real call), then the limiter around that (every attempt is limited), then retry around everything. The order is the design:
- Accounting **inside** retry: each retry attempt is its own row.
- Limiter **inside** retry: each retry attempt waits its turn, so a burst of retries cannot break the per-minute limit.
- Line 130: the per-minute limit applies only to `hosted` (`LLM_REQUESTS_PER_MINUTE`, from the Gemini free tier of 15 per minute). Local and Anthropic get `0` (no per-minute limit).
- Line 123's annotation `client: LLMClient` lets the same variable hold each wrapper in turn (each is an `LLMClient`).

## Lines 135 to 171: `_adapter` (builds the real provider)
| Line | Meaning |
|---|---|
| 137 | `httpx2.Timeout(LLM_TIMEOUT_SECONDS, connect=5.0)`: the read time-out is the setting (60 s), but **connecting** gets only 5 s. A dead host fails fast and the retry layer reacts, instead of waiting a full minute to find out |
| 138 | The comment that matters: **`max_retries=0` everywhere**. The SDKs retry by themselves (2 times by default). My retry layer does the retrying, and both together would multiply the calls (3 x 3 = 9). Day 5's 182-second stuck call was exactly this multiplication |
| 139 to 153 | **hosted**: needs `LLM_API_KEY` **and** `LLM_MODEL`, else `LLMNotConfiguredError` (503). `get_secret_value()` reads the key out of its `SecretStr` wrapper only here, at the last moment. Base URL is Gemini's OpenAI-compatible URL |
| 154 to 165 | **anthropic**: needs `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` |
| 166 to 171 | **local**: Ollama ignores the key, but the SDK refuses an empty one, so the placeholder string `"ollama"` is used |

Each created SDK client is appended to `_sdk_clients` (150, 164, 170).

## Lines 173 to 175: `aclose`
Closes every SDK client (releases their HTTP connection pools). Called from `main.py`'s `lifespan` at shutdown.

---

## How it connects
- `main.py` creates it once: `SettingsLLMRegistry(get_settings(), DbCallRecorder(async_session_factory))` and stores it in `app.state.llm`.
- `api/deps.py`'s `get_llm_registry` reads it back from `request.app.state.llm` (how `app.state` and the lifespan work: `notes/day-3/14-lifespan-and-shared-client.md`).
- Tests replace it with `FakeRegistry` (`tests/fakes.py`), and test this class directly in `tests/test_llm_registry.py`.

## Quick check
- Why is the stack built from the inside out: adapter, accounting, limiter, retry?
- Why does `_route` swallow `LLMNotConfiguredError` for the fallback but not for the primary?
- Why `max_retries=0` on the SDK clients?
- Why is the per-minute limit only set for `hosted`?
