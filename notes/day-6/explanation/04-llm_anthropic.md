# `services/llm_anthropic.py`: the adapter for Anthropic's Messages API

**File:** `src/ai_service/services/llm_anthropic.py` (185 lines, new on Day 6)
**Job:** the second provider adapter the plan asks for. It makes the **Anthropic SDK** look like the same `LLMClient` as `03-llm_openai.md`, so the rest of the app cannot tell the two apart. It is the only file that imports `anthropic`.

**Honesty note:** this project has no Anthropic key, so this adapter was **never run against the real service**. It is tested against a fake HTTP server built from Anthropic's documented message and stream formats (`tests/test_llm_anthropic.py`, 14 tests). The Gemini and Ollama adapters were run live.

The point of having it: it shows what an adapter really hides. Anthropic differs from the OpenAI style in five ways (lines 3 to 9 of the file), and none of them leak out of this file.

---

## Lines 1 to 10: docstring = the five differences
| Difference | Where handled |
|---|---|
| The system prompt is a separate `system` parameter, not a message | `split_system` (line 96) |
| The reply is a list of **content blocks**; `max_tokens` is **required** | `generate` joins text blocks (142); `_args` always sends `max_tokens` (120) |
| No native JSON-schema switch: a **forced tool** whose input schema is my schema | `generate_structured` (145 to 165) |
| Cached input is reported **apart** from `input_tokens`, and marked with `cache_control` | `usage_from_anthropic` (86), `split_system` (103) |
| Other stop-reason names | `_STOP_REASONS` (49) |

## Lines 12 to 47: imports and logger
Same pattern as the OpenAI adapter: standard library, then the SDK (`AnthropicError` is the base exception, then the connection, status, timeout classes and `AsyncAnthropic`), then my types. `json` is new: the forced tool returns a Python dict, and my protocol returns **JSON text**, so line 163 needs `json.dumps`.

## Lines 49 to 55: `_STOP_REASONS`
```python
"end_turn": STOP, "stop_sequence": STOP, "tool_use": STOP, "max_tokens": LENGTH, "refusal": CONTENT_FILTER
```
Translates Anthropic's names to my shared vocabulary (`01-llm_types.md`, lines 14 to 18). `tool_use` becomes `STOP` because for structured output the forced tool call **is** a normal successful end. Anything not in the table passes through unchanged (see line 131: `.get(stop, stop)`).

## Lines 58 to 63: `_retry_after`
Reads the `retry-after` header only (Anthropic sends it; unlike Gemini there is no text to parse). `None` if absent, `None` if it is an HTTP date (`ValueError`).

## Lines 66 to 83: `map_anthropic_error`
Same shape as the OpenAI mapper; the differences are small and instructive:
| Line | Difference |
|---|---|
| 67 to 70 | Same order: timeout (child) before connection (parent) |
| 74 to 75 | **Any** 429 is `RateLimitedError`. There is no daily-quota text heuristic here because I have no real error body to base it on, and I do not guess |
| 78 | Context too long: 413, or 400 whose message contains `too long` (Anthropic's wording is "prompt is too long: N tokens > M maximum") |
| 80 | `status == 529` is Anthropic's **overloaded** status. Together with 408, 409 and every 5xx, it becomes `OverloadedError` |

## Lines 86 to 93: `usage_from_anthropic`
```python
Usage(
    input_tokens=...("input_tokens"),
    output_tokens=...("output_tokens"),
    cache_read_tokens=...("cache_read_input_tokens"),
    cache_write_tokens=...("cache_creation_input_tokens"),
)
```
Here **no subtraction is needed**: Anthropic's `input_tokens` already **excludes** the cached parts, which arrive in two separate fields. (Compare `usage_from_openai`, which must subtract.) `getattr(..., 0) or 0` guards against a missing field or a `None`. `cache_write_tokens` matters only here: Anthropic charges **more** for writing to the cache, so the cost formula has a separate price for it.

## Lines 96 to 105: `split_system`
Anthropic wants `system` apart from `messages`.
| Line | Meaning |
|---|---|
| 98 to 100 | Every message whose role is `system` becomes a text **block** `{"type": "text", "text": ...}` |
| 101 to 103 | If the caller asked for caching (`cache=True`) and there is a system block, the **last** one gets `"cache_control": {"type": "ephemeral"}`. Everything from the start up to and including that block is then cached (Anthropic caches in the order tools, then system, then messages) |
| 104 | The rest (user and assistant messages) as plain dicts, typed `Any` for the same strict-typing reason as `_params` |
| 105 | Returns both parts |

The `*` in the signature makes `cache` keyword-only, so a call reads `split_system(messages, cache=True)` and cannot be mistaken.

## Lines 108 to 114: the class
`backend = "anthropic"` is a **class attribute** (every instance is the same backend). `__init__` stores the client and the default cap; `model` is public (the `LLMClient` protocol needs it).

## Lines 116 to 125: `_args`
Builds the keyword arguments that `generate` and `generate_structured` both send, so they are written once:
`model`, `max_tokens` (the request's cap, else the default; **always present**, the API requires it), `messages`; and `system` only if there is one (an empty `system` list would be an error).

## Lines 127 to 135: `_response`
Builds an `LLMResponse` from an Anthropic `Message`: the given text; the stop reason translated through the table (and `None` if there is none); the normalised usage; the model and backend names.

## Lines 137 to 143: `generate`
`messages.create(**args)`, then join every block whose type is `"text"` (a reply can hold several blocks, and other kinds such as `tool_use`). Errors map through `map_anthropic_error`.

## Lines 145 to 165: `generate_structured` (tool as schema)
Anthropic (in this adapter) has no "reply in this JSON schema" setting, so it uses the older but universal method from Day 5 `3.structured-output.md`:
| Line | Meaning |
|---|---|
| 149 to 155 | Declare **one tool** named after my schema, with `input_schema = schema`. The tool does nothing; it exists only to carry the shape |
| 156 | `tool_choice = {"type": "tool", "name": ...}`: **force** the model to call that tool |
| 157 to 160 | Send; map errors |
| 161 to 163 | Find the `tool_use` block. Its `input` is a dict that follows my schema; `json.dumps(block.input)` turns it into the JSON text my protocol returns |
| 164 to 165 | No tool block means a refusal (`stop_reason` `refusal` becomes `content_filter`) or a cut-off before the call. Return empty text with the real stop reason, so `extract_service` handles it like any other refusal |

## Lines 167 to 184: `stream`
The Anthropic SDK offers a context manager (`async with client.messages.stream(...) as stream`). A generator cannot use `async with` and `yield` as cleanly while keeping explicit control of closing, so the code calls `__aenter__` and `__aexit__` by hand:
| Line | Meaning |
|---|---|
| 169 to 172 | Open: `manager = ...stream(...)`, then `stream = await manager.__aenter__()`. Failures here are mapped (the "provider is down" case) |
| 174 | `yield StreamStart` |
| 175 to 177 | `stream.text_stream` yields only the **text pieces** of the text deltas; skip empty strings; `yield TextDelta` |
| 178 | After the text: `get_final_message()` gives the complete message with `stop_reason` and `usage` (Anthropic reports them at the end) |
| 179 to 180 | Reuse `_response` to translate the stop reason and usage, then `yield Finish(...)` |
| 181 to 182 | Mid-stream failures are mapped |
| 183 to 184 | `finally: await manager.__aexit__(None, None, None)` closes the upstream call on every exit, including a consumer that stops early (the same disconnect guarantee as the OpenAI adapter) |

---

## How it connects
- Selected with `{"backend": "anthropic"}` and configured by `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` (`config.py`, built in `llm.py`).
- Can be the **fallback** target (`LLM_FALLBACK_BACKEND=anthropic`).
- Prompt caching: the route sets `cache_system=True`; only this adapter turns it into `cache_control`.

## Quick check
- Which of the five differences would break the cost numbers if the adapter ignored it?
- Why does `generate_structured` use a forced tool?
- Why does `usage_from_anthropic` not subtract anything?
- What does `tool_use` map to in `_STOP_REASONS`, and why?
