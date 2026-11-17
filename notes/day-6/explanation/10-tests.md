# The Day 6 tests: what each file proves

Day 5 ended with **73** tests; Day 6 ends with **162**. The new and changed test files:

| File | Tests | Status |
|---|---|---|
| `tests/test_llm_wrappers.py` | 21 | new |
| `tests/test_llm_accounting.py` | 13 | new |
| `tests/test_llm_anthropic.py` | 14 | new |
| `tests/test_llm_registry.py` | 8 | new |
| `tests/test_llm_provider.py` | 20 | rewritten for the new adapter, plus new error-mapping tests |
| `tests/test_extract.py` | 24 | extended (repair, refusal, sanity checks, connection give-back) |
| `tests/test_chat.py` | 20 | extended (labels, cache flag, model name after fallback) |
| `tests/fakes.py` | n/a | the fake model, rewritten for `LLMClient` |

Run them: `uv run pytest` (about 13 seconds, no network, no key).

**The testing idea for the whole layer:** every layer is an `LLMClient`, so each one is tested **alone** with a **scripted** client that raises or returns what the test says, and with a **fake clock** so "wait 60 seconds" takes no time. No test calls a real model.

---

# `tests/fakes.py`: the fake model
- `reply(text, stop_reason)` builds a scripted `LLMResponse` (with `Usage(100, 40)`) for structured answers.
- `FakeProvider` fits `LLMClient`: scripted `texts` to stream, scripted `json_replies` for structured calls, switches to fail (`fail_before_first`, `fail_at`, `fail_json`, with a chosen `error`), delays (`delay`, `first_delay`), and it **records** what it received (`requests`, `json_calls`) and whether the stream was closed (`closed`).
- `stream()` now yields a `StreamStart` first, then `TextDelta`s, then a `Finish(Usage)`.
- `FakeRegistry` hands out a hosted and a local fake. The `conftest.py` overrides `get_llm_registry` with it, so the app under test never touches the network.

---

# `tests/test_llm_wrappers.py` (21 tests)
A helper class `Scripted` answers each call from a list (an exception is raised, anything else returned). A `Clock` object is a time that only moves when a test sleeps and records every sleep, so tests assert the **exact waits**.

**Retry**
| Test | Proves |
|---|---|
| `test_a_transient_error_is_retried_with_growing_waits` | two failures then success; sleeps are `[1.0, 2.0]` (base x 2^n) |
| `test_jitter_spreads_the_wait_between_zero_and_the_ceiling` | jitter 0.25 gives a wait of 0.25 s |
| `test_errors_that_waiting_cannot_fix_are_not_retried` (3 cases) | `AuthError`, `ContextTooLongError`, `QuotaExhaustedError` are raised after **one** call |
| `test_it_gives_up_after_the_attempts_and_raises_the_last_error` | 3 attempts, 2 sleeps, the last error raised |
| `test_retry_after_from_the_provider_is_obeyed` | `retry_after=7` makes the wait 7 s, though jitter alone said 0 |
| `test_it_stops_when_the_next_wait_would_pass_the_time_budget` | `retry_after=60` with a 30 s budget: gives up at once, no sleep |
| `test_structured_calls_are_retried_too` | `generate_structured` is covered by the same loop |
| `test_a_stream_is_retried_while_no_text_has_been_sent` | a 429 before any text, then a good stream: the events have **one** `StreamStart` and the text once; both attempts' streams were closed |
| `test_a_stream_is_not_retried_after_text_was_sent` | an error after `"Hel"`: raised, **one** call (a retry would show "Hel" twice) |

**Fallback**
| Test | Proves |
|---|---|
| `test_the_second_backend_answers_when_the_first_keeps_failing` | the response names the second backend and model |
| `test_the_primary_is_used_when_it_works` | the second client is never called |
| `test_a_quota_error_moves_on_to_the_next_backend` | `fallback_ok` without `retryable` still falls back |
| `test_errors_another_provider_would_not_fix_are_raised_at_once` (2 cases) | `AuthError` and `ContextTooLongError` do not fall back |
| `test_when_every_backend_fails_the_last_error_is_raised` | the error of the last backend is the one raised |
| `test_a_stream_falls_back_before_the_first_text` | a stream that fails before text moves to the next client; the first was closed |
| `test_a_stream_that_breaks_after_text_does_not_fall_back` | an error after text is raised; the second client is never called |

**Limits**
| Test | Proves |
|---|---|
| `test_at_most_n_calls_run_at_the_same_time` | 6 calls at once, `max_concurrency=2`: the peak in flight is 2 |
| `test_the_per_minute_limit_makes_the_next_call_wait` | 3 per minute: the 4th waits `60.0` s (fake clock); the 5th then does not need to wait |

---

# `tests/test_llm_accounting.py` (13 tests)
A `MemoryRecorder` keeps the records in a list (and can be told to break).

**Cost**
- the cost is the sum of the four token kinds at their own prices: `(1000 x 0.25 + 500 x 1.50 + 2000 x 0.025) / 1e6 = 0.00105000`;
- the cache-write price is its own number (3.75 USD per million);
- an unknown usage or price gives `None`, but a model with a **price of zero** gives `0`;
- the default price table knows `gemini-3.1-flash-lite` (cache read cheaper than input) and `gemma3:270m` (free).

**The wrapper**
- a success is recorded with tokens, cost, context, backend, model;
- a failure is recorded with `error_type="RateLimitedError"`, no usage, no cost, and the error is **still raised**;
- **every retry is its own row** (`["error", "ok"]`): accounting inside retry;
- a finished stream is recorded with its final usage;
- a stream the reader abandons after two events is recorded `cancelled` with no usage, and the upstream was closed;
- a model with no price is logged with no cost;
- **a recorder that raises never breaks the call**;
- the **log line** carries `cache_read_tokens=90`, the tokens, `cost_usd == "0.00001225"` (that is `(2.5 + 7.5 + 2.25) / 1e6`), the feature, request id and backend;
- the real `DbCallRecorder` saves one row in the test database (an unreadable `user_id` becomes `NULL`).

---

# `tests/test_llm_provider.py` (20 tests): the OpenAI-style adapter against a fake HTTP server
The OpenAI SDK has its own HTTP library (`httpx2`), so `respx` cannot intercept it; `httpx2.MockTransport` plays the server and records what the SDK sent.
- the stream yields `StreamStart`, the text, then `Finish(Usage(7, 2))`; the request had `stream=True` and `include_usage`;
- a 500 before the first byte is an `OverloadedError`;
- structured output sends `response_format` with the schema and `strict`, `temperature 0`, and reads the usage; a per-call `max_tokens` overrides the default; **no usage block gives `usage is None`**;
- a 429 with `retry-after: 7` is a `RateLimitedError` with `retry_after == 7`;
- **cached tokens are counted apart**: `prompt_tokens 1000` with `cached_tokens 800` gives `Usage(200, 20, cache_read=800)`;
- a blocked prompt with no choices is a `content_filter` stop;
- **11 status cases** in one parametrised test (429 rate vs quota, 500, 503, 401, 403, 400 too long, 413, 400 other, 404) map to the right error type and `retryable` flag;
- a connection failure and a timeout are retryable;
- **Gemini's wait in the error text**: a 429 with no header and `"Please retry in 23.605992143s."` gives `retry_after ≈ 23.6`.

# `tests/test_llm_anthropic.py` (14 tests): the same for Anthropic
- the system prompt is sent apart, with `cache_control` when asked and without it otherwise; no system message in the list; `max_tokens` always sent;
- text, stop reason and usage are normalised (`Usage(12, 5, cache_read=800, cache_write=40)`, `prompt_tokens == 852`);
- 3 stop-reason translations;
- structured output forces a tool and returns its arguments as JSON;
- a refusal with no tool call is empty text and `content_filter`;
- a stream (built from Anthropic's event format) yields `StreamStart`, two texts and a `Finish` with the cache usage;
- 5 HTTP statuses (429, 529, 500, 401, 400 too long) map to the shared errors.

# `tests/test_llm_registry.py` (8 tests)
Each backend is a `RetryingClient` with the right `backend` and `model`; the same object is returned twice; the SDK clients have `max_retries == 0`; a configured fallback gives a `FallbackClient`; an **unconfigured fallback is skipped, not fatal**; a backend with no key raises `LLMNotConfiguredError`; the system prompt comes from the file when set; the shipped prompt file is longer than 16,000 characters; blank `.env` values mean "not set".

---

# `tests/test_extract.py` (24 tests, 11 new)
The Day 5 ones were updated to the new response type. New:
- **two repairs, success on the third try**: `attempts == 3`, input tokens 300, and the third prompt has the six messages `system, user, assistant, user, assistant, user`;
- a **refusal** is `422 EXTRACTION_REFUSED` with **one** call;
- the call is labelled with the feature `extract`, the request id `req-123`, a tenant and a user;
- `fallback_used` is `True` when another backend answered;
- **7 sanity-check cases** (bad phone, short phone, bad email, huge budget, negative budget, long name, long city): the first reply is repaired, and the repair prompt names the field and the complaint;
- a model that keeps returning a bad phone ends in a **handled** `422` whose details name `phone`;
- ordinary values (a Gujarati name, `+91 98765-43210`, a budget of 0) are accepted;
- the sanity checks are **not** in the JSON schema sent to the model;
- **the database connection is given back before the model is called**: a spy session records `in_transaction()` at the moment of the model call and it must be `False`. I confirmed the test **fails** with the `session.commit()` line removed.

# `tests/test_chat.py` (20 tests, 3 new)
- the call carries `cache_system=True`, the system message first, the new message last, and the feature, request id, tenant and user;
- the `done` event reports `cache_read_tokens` (`Usage(10, 5, 90)` gives input 100, output 5, cached 90);
- the saved message and the `start` event name the model that really answered (a fallback model).

---

## The quality gates at the end of Day 6
- `uv run pytest`: **162 passed**
- `uv run mypy`: no issues in 59 files (strict)
- `uv run ruff check src tests scripts`: clean, except `core/middlewares.py:64` (101 characters), which was over 100 before Day 6.

## Quick check
- Why are the wrappers tested with a fake clock?
- Which test proves that a stream is never retried after its first word?
- How do I know the connection-give-back test really tests the bug?
- Which tests prove "valid is not correct" and what do they do about it?
