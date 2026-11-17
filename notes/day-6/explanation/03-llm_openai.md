# `services/llm_openai.py`: the adapter for Gemini, OpenAI and Ollama

**File:** `src/ai_service/services/llm_openai.py` (214 lines, new on Day 6; the Day 5 class in `llm.py` was split out and grown)
**Job:** turn the OpenAI Python SDK into an `LLMClient` (see `01-llm_types.md`). Three servers speak the OpenAI chat-completions protocol, so **one class** serves them: Gemini (its OpenAI-compatible URL), OpenAI itself, and Ollama. Only the base URL, key and model name differ, and those are set when the object is built (in `llm.py`). This is the **only file that imports the `openai` package**.

What an adapter must do, in three jobs:
1. send the request in the provider's format (`_params`, the `create(...)` calls);
2. turn the answer into my types (`LLMResponse`, `Usage`, stream events);
3. turn every failure into one of **my** error types (`map_openai_error`).

---

## Lines 1 to 5: docstring
States the "only file that imports the OpenAI SDK" rule.

## Lines 7 to 19: imports
| Line | Import | Used for |
|---|---|---|
| 7 | `logging` | the logger on line 42 |
| 8 | `re` | the regular expression on line 58 |
| 9 | `AsyncGenerator` | the return type of `stream` |
| 10 | `Any, cast` | `Any` for SDK objects whose types are too strict; `cast` to tell mypy a dict is the SDK's `response_format` type |
| 12 | `httpx2` | the HTTP library **the OpenAI SDK uses** (a fork of httpx). Needed only for its `ResponseNotRead` error on line 71 |
| 13 to 19 | SDK exception classes | `OpenAIError` is the base of everything the SDK raises; `APIStatusError` has a status code (4xx, 5xx); `APIConnectionError` is "could not reach the server"; `APITimeoutError` is its **child** "took too long"; `AsyncOpenAI` is the async client |

Lines 21 to 40 import my own types from `llm_types`: the error classes, `LLMRequest`/`LLMResponse`, the stream events and `Usage`.

## Line 42: the logger
`logging.getLogger("ai_service.llm")`: the same logger name `AccountingClient` and the retry layer use, so all LLM log lines share one name and can be filtered together.

## Lines 44 to 53: the two keyword lists
```python
_CONTEXT_HINTS = ("context length", "context_length", "maximum context", "too long", ...)
_DAILY_QUOTA_HINTS = ("insufficient_quota", "per day", "perday", "daily")
```
HTTP status alone is not enough to tell two kinds of failure apart:
- A **400** can mean "bad parameter" (never retry) or "your input is longer than the model's window" (also never retry, but it needs a different error: `ContextTooLongError`). The provider only says which in the **message text**, so the code looks for these phrases.
- A **429** can mean "too many per minute" (wait and retry) or "daily quota used up" (retrying is pointless). Again only the text tells (`per day`, `insufficient_quota`).

These are heuristics: if a provider changes its wording the error falls back to the safer default (a plain 429 is retried; a plain 400 is `BadRequestError`).

## Lines 56 to 58: `_RETRY_IN_TEXT`
```python
_RETRY_IN_TEXT = re.compile(r"retry in ([0-9]+(?:\.[0-9]+)?)\s*s", re.IGNORECASE)
```
Found by the live test (`gotchas.md`): **Gemini's 429 has no `retry-after` header**; the body says `Please retry in 23.605992143s.`. The regex reads it:
- `retry in ` the literal words, case-insensitive;
- `([0-9]+(?:\.[0-9]+)?)` capture group 1: digits, optionally a `.` and more digits (`23.605992143`);
- `\s*s` optional spaces then the letter `s` (seconds).

## Lines 61 to 73: `_retry_after(exc)`
| Line | What it does |
|---|---|
| 63 | Reads the standard `retry-after` header |
| 64 to 68 | If present, tries `float(raw)`. `max(..., 0.0)` stops a negative number. `ValueError` happens when the header is an HTTP **date** instead of seconds (allowed by the standard); then it does nothing (`pass`) and falls through to the text |
| 69 to 72 | Searches the **body text**. `exc.response.text` can raise `ResponseNotRead` if the body was never read (a streamed response); then it gives up with `None` |
| 73 | Returns the number from the text, or `None`. The retry layer then falls back to its own backoff |

## Lines 76 to 97: `map_openai_error(exc, what)`: the heart of the file
Input: an SDK exception and a short phrase `what` ("the call failed"). Output: one of my errors (it **returns** the error; the caller raises it with `raise ... from exc`, so the original is chained).

| Line | Check | Result |
|---|---|---|
| 78 | `APITimeoutError` **first**, because it is a subclass of `APIConnectionError`; checking the parent first would hide it | `LLMTimeoutError` |
| 80 | `APIConnectionError` | `LLMConnectionError` |
| 82 | `APIStatusError`: the server answered with an error status | continues below |
| 83 | `status = exc.status_code` | e.g. 429 |
| 84 | `text = f"{exc.code or ''} {exc.message}".lower()`: provider error code plus message, lower-cased once, used by the keyword checks | |
| 85 | `message` is what ends in the logs: `"the call failed: HTTP 429: ..."` | |
| 86 to 89 | **429**: if the text has a daily-quota hint, `QuotaExhaustedError` (not retried, fallback ok). Else `RateLimitedError` with `retry_after=_retry_after(exc)` | |
| 90 to 91 | **401, 403** to `AuthError` | |
| 92 to 93 | **413**, or **400 with a context hint**, to `ContextTooLongError` | |
| 94 to 95 | **408, 409, or any 5xx** to `OverloadedError`, also with `retry_after` | |
| 96 | Any other status (400, 404, 422 ...): `BadRequestError` | |
| 97 | Anything else from the SDK (not a connection or a status error): a plain `LLMError`, not retryable | |

This function is tested row by row in `tests/test_llm_provider.py::test_each_failure_becomes_the_right_error_type`.

## Lines 100 to 102: `_params`
```python
return [{"role": m.role, "content": m.content} for m in messages]
```
Turns my `ChatMessage` objects into the dicts the SDK sends. It returns `Any` because the SDK's own `messages=` type is a strict union of many message kinds, and a plain `list[dict[str, str]]` does not satisfy strict mypy even though it works at runtime. (Same function as Day 5's `_as_params`.)

## Lines 105 to 114: `usage_from_openai(usage)`
Normalises token counts (the trap explained in `01-llm_types.md`):
| Line | Meaning |
|---|---|
| 107 | `prompt_tokens_details` exists only when the provider sends it; `getattr(..., None)` avoids an error when it is missing |
| 108 | `cached_tokens` inside it, or 0. `int(... or 0)` turns `None` into 0 |
| 109 | `prompt_tokens`, the **total** input (includes the cached part) |
| 111 | `input_tokens = prompt - cached`, clamped at 0 with `max`: this is **new** input only |
| 112 | `output_tokens` from `completion_tokens` |
| 113 | `cache_read_tokens = cached` |

Real example from the live run: Gemini reported `prompt_tokens = 4969` and `cached_tokens = 2030`, so `Usage(input_tokens=2939, output_tokens=114, cache_read_tokens=2030)`.

## Lines 117 to 129: `OpenAICompatProvider.__init__`
| Line | Meaning |
|---|---|
| 120 | `client: AsyncOpenAI`, **built by the registry** (with the URL, key and timeout); the adapter does not build its own, so tests can pass a client wired to a fake server |
| 121 to 122 | `model` name and the default output-token cap |
| 123 | the `*` makes `backend` keyword-only; default `"hosted"` |
| 126 to 129 | Stores them. `model` and `backend` are public (the `LLMClient` protocol needs them); the client and the cap are private (leading underscore) |

## Lines 131 to 140: `generate`
A plain non-streaming call: `chat.completions.create(model, messages, max_tokens)`. `request.max_tokens or self._max_output_tokens` means "the request's cap if it gave one, else the default". Any `OpenAIError` is turned into my error with `raise map_openai_error(exc, "the call failed") from exc` (`from exc` keeps the original in the traceback). Then `_to_response` builds the answer.

## Lines 142 to 161: `generate_structured`
Same as `generate`, plus:
- `temperature=0` (149): the most predictable output; extraction should not be creative.
- `response_format` (151 to 157): the **native structured output** switch. `"type": "json_schema"` with `"strict": True` makes the provider constrain its tokens to my schema. `cast(Any, {...})` is only there to satisfy the SDK's strict typing.
Validating the JSON is **not** done here (the protocol says it is the caller's job); the adapter returns the raw text.

## Lines 163 to 175: `_to_response`
| Line | Meaning |
|---|---|
| 164 | Usage is `None` if the provider sent no `usage` block |
| 165 to 167 | **No `choices` at all.** Gemini answers a blocked prompt this way, so it is reported as an empty text with `stop_reason = CONTENT_FILTER` (a refusal), not as a crash |
| 168 to 175 | Normal case: first choice. `message.content or ""` (content can be `None`), `finish_reason` as the stop reason (OpenAI-style names `stop`, `length`, `content_filter` already equal my shared vocabulary), the usage, and the model and backend names |

## Lines 177 to 206: `stream`
The streaming version. An `async def` with `yield` inside is an **async generator**.
| Line | Meaning |
|---|---|
| 178 to 187 | Opens the upstream stream. Errors **here** (before anything is yielded) are mapped and raised: this is the "provider is down" case the route can still turn into a clean 502 |
| 184 | `stream_options={"include_usage": True}`: ask for token counts in the last chunk (Day 5 `2.streaming.md`) |
| 188 | A second `try` for everything that can fail **while** reading |
| 189 | `yield StreamStart(...)`: the first event, no text |
| 190 to 191 | Variables to remember the stop reason and usage until the end |
| 192 | `async for chunk in stream` reads the chunks |
| 193 to 194 | A chunk with `usage` (the last one) updates the usage |
| 195 to 196 | A usage-only chunk has no `choices`; skip it |
| 198 to 199 | If the chunk has text, `yield TextDelta(...)` (some chunks have only a role) |
| 200 to 201 | Remember the `finish_reason` |
| 202 | After the loop: `yield Finish(stop_reason, usage)` |
| 203 to 204 | A failure mid-stream is mapped to my errors and raised |
| 205 to 206 | `finally: await stream.close()` runs on every exit: normal end, error, **or the consumer closing the generator** (a client who left). Closing the SDK stream closes the HTTP connection, so the provider **stops generating**: no tokens are produced or paid for nobody (the Day 5 disconnect lesson) |

## Lines 209 to 213: `OllamaProvider`
A subclass that only passes `backend="local"` to the parent. Ollama speaks the same protocol, so there is nothing else to change. It is a separate class so the plan's "Ollama adapter" is a visible, selectable thing and so the log line says `local`.

---

## How it connects
- Built by `SettingsLLMRegistry._adapter` in `llm.py` with `max_retries=0` on the SDK client (my retry layer does the retrying).
- Wrapped by `AccountingClient`, `LimitedClient`, `RetryingClient` (see `06-llm_wrappers.md`, `05-llm_accounting_and_cost.md`).
- Tested in `tests/test_llm_provider.py` against a fake HTTP server (`httpx2.MockTransport`).

## Quick check
- Why is `APITimeoutError` checked before `APIConnectionError`?
- Where does Gemini put the time to wait after a 429, and how does the code read it?
- Why does `usage_from_openai` subtract `cached_tokens`?
- What closes the upstream call when a client leaves a stream, and which line is it?
