# `services/llm_accounting.py` and `services/llm_cost.py`: what every call costs

**Files:**
- `src/ai_service/services/llm_cost.py` (27 lines): tokens to money.
- `src/ai_service/services/llm_accounting.py` (260 lines): records **every real call** as one JSON log line and one `llm_calls` database row.

**Job (plan task 2):** "a wrapper that logs per request: model, input/output/cached tokens, cost, latency, request ID, tenant." The wrapper (`AccountingClient`) sits **closest to the provider** in the stack, so it sees every real HTTP call, including each retry and each fallback made by the layers above it. That is why the table has **one row per provider call**, not per user request.

---

# Part 1: `llm_cost.py`

## Lines 3 to 6: imports
`Decimal` (exact decimal arithmetic), `ModelPrice` (the price record from `config.py`) and `Usage`.

## Lines 8 and 9: two constants
```python
_MILLION = Decimal(1_000_000)
_EIGHT_PLACES = Decimal("0.00000001")
```
Prices are "USD per **million** tokens", so the sum is divided by `_MILLION`. `_EIGHT_PLACES` is the rounding step (8 decimal places) that matches the database column `NUMERIC(14, 8)`. A call that costs a hundred-thousandth of a dollar still shows as `0.00001225`.

## Lines 12 to 26: `compute_cost(usage, price)`
| Line | Meaning |
|---|---|
| 12 | Takes a `Usage | None` and a `ModelPrice | None`; returns `Decimal | None` |
| 18 to 19 | **If the usage is unknown or the model has no price, return `None`**, never `0`. A 0 would look like "free" and hide a missing measurement (the "None is not 0" rule from `01-llm_types.md`) |
| 20 to 25 | The formula: new input x input price, plus output x output price, plus cache-read x cache-read price, plus cache-write x cache-write price |
| 21 | `Decimal(str(price.input))`: the prices are floats in the settings (`0.25`); converting through `str` gives the exact decimal `0.25`. `Decimal(0.25)` straight from a float can carry binary rounding noise |
| 26 | Divide by a million and `quantize` to 8 places |

**Worked example from the real run** (Gemini 3.1 Flash-Lite: input 0.25, output 1.50, cache-read 0.025 USD per million). `/chat` turn 2: 2,939 new input, 2,030 cached, 114 output:
```
2939 x 0.25  = 734.75
 114 x 1.50  = 171.00
2030 x 0.025 =  50.75
total        = 956.50   /1,000,000 = 0.00095650 USD
```
The log line printed exactly `"cost_usd": "0.00095650"`. The same turn **without** caching: 4,969 x 0.25 + 171 = 1,413.25 so `0.00141325`; caching saved 32%.

---

# Part 2: `llm_accounting.py`

## Lines 7 to 30: imports
`asyncio` (for `CancelledError`), `time` (latency), `uuid` (parse ids), `Mapping` (the price table type), `dataclass`, `Decimal`, `Protocol`, `anyio` (shielded clean-up), SQLAlchemy's async session types, the model `LLMCall` and its three status constants, `compute_cost`, and my LLM types.

## Lines 35 to 49: `LLMCallRecord`
A frozen dataclass holding **everything about one call**: the labels (`request_id`, `tenant_id`, `user_id`, `feature`), what ran (`backend`, `model`, `operation`), how it ended (`status`, `error_type`, `stop_reason`), the numbers (`usage`, `cost_usd`, `latency_ms`). It is the one object the log line and the database row are both built from, so they cannot disagree.

## Lines 52 to 53: `CallRecorder` protocol
```python
class CallRecorder(Protocol):
    async def record(self, call: LLMCallRecord) -> None: ...
```
"Something that can save a call." Production uses `DbCallRecorder`; tests use an in-memory recorder (`MemoryRecorder` in `tests/test_llm_accounting.py`); scripts can pass `None`. The accounting wrapper does not know or care how it is saved.

## Lines 56 to 60: `_as_uuid`
Turns the string `tenant_id` into a `uuid.UUID`, or `None` if the string is empty or not a valid UUID (`ValueError`). The context carries ids as **strings** (it is made of plain values); the table wants real UUIDs. A bad id must **not** make the save fail, so it becomes `NULL`.

## Lines 63 to 92: `DbCallRecorder`
| Line | Meaning |
|---|---|
| 66 to 67 | Gets the **session factory** (not a session) |
| 71 | `async with self._session_factory() as session`: a **short session of its own** for each save. The request's session is no use: for a stream it is long gone, and a retry's row must be saved even if the request failed |
| 72 to 91 | Builds an `LLMCall` row from the record. The four token columns use `x.field if usage else None`, so an unknown usage is saved as **`NULL`**, not 0 |
| 92 | `commit()` |

## Lines 95 to 107: `AccountingClient.__init__`
Wraps one client (`inner`). `prices` is the table from the settings (`LLM_PRICES`); `recorder` is optional. It copies `backend` and `model` from `inner` as every wrapper does.

## Lines 111 to 123: `generate` and `generate_structured`
Both delegate to `_timed` with an **operation name** (`"generate"`, `"structured"`) and a lambda that makes the real call. The operation name goes into the row so I can tell chat calls from extraction calls.

## Lines 125 to 156: `stream` (the careful part)
A stream may end in four ways: normally, with a provider error, because the **client left**, or because the task was **cancelled**. The row must be written in all four.
| Line | Meaning |
|---|---|
| 126 to 130 | Start the timer; open the inner stream; the default outcome is `ok`; `finish` will remember the `Finish` event; `model` defaults to the wrapped client's model |
| 132 to 135 | Pass every event on (`yield event`) and **remember the `Finish`** (it carries the stop reason and the usage) |
| 136 to 138 | A provider error mid-stream: record status `error` and the error **kind** (the class name), then `raise` it unchanged so the layers above can react |
| 139 to 142 | `except asyncio.CancelledError, GeneratorExit:` (the Python 3.14 form without brackets). `CancelledError` = the task was cancelled; `GeneratorExit` = the consumer closed the generator (the client left). If **no `Finish` was seen**, the stream was cut short, so status `cancelled`. If a `Finish` **was** seen, the consumer simply closed after the end, which is not a cancellation, and the status stays `ok`. Then `raise` again |
| 143 to 156 | `finally`, always: inside `anyio.CancelScope(shield=True)` (so a cancellation cannot interrupt it), close the inner stream (stops the upstream call), then `_finish(...)` writes the log line and the row |

For a cancelled stream `usage` is `None` (the provider never sent it), so the row has `NULL` tokens and `NULL` cost. The tokens already generated **are** billed by the provider; that cost is simply not measured here (a limitation noted in the Day 5 notes: "the provider only sends them at the end").

## Lines 160 to 193: `_timed` (non-streaming)
The same idea for `generate` and `generate_structured`:
| Line | Meaning |
|---|---|
| 161 | Start the timer |
| 163 | `await call()`: the real call |
| 164 to 173 | `LLMError`: record an `error` row with the error kind, then **re-raise** so retry and fallback layers still see it |
| 174 to 183 | `CancelledError`: record `cancelled` inside a shielded scope, then re-raise |
| 184 to 193 | Success: record `ok` with the response's **actual** model, stop reason and usage; return the response unchanged |

Only `LLMError` and `CancelledError` are caught. A real bug (a `KeyError`) is **not** swallowed: it propagates.

## Lines 195 to 259: `_finish` (log line and row)
| Line | Meaning |
|---|---|
| 207 | `latency_ms`: seconds since the timer, times 1000, rounded to 0.1 ms. `perf_counter` is the precise clock for measuring durations |
| 208 | `cost = compute_cost(usage, self._prices.get(model))`: price lookup by the model that **answered**; `None` for an unknown model |
| 209 to 224 | Build the `LLMCallRecord` |
| 225 to 251 | **The log line.** `logger.log(level, "llm %s %s: %s %s, %s ms", ...)`: `INFO` for `ok`, `WARNING` otherwise (failed and cancelled calls stand out). The text is short and human; the structured values go in `extra=`, which the JSON formatter prints because their names were added to `core/logging.py`'s list. `cost_usd` is turned into a **string** (`"0.00095650"`) because JSON has no Decimal and a float would lose digits |
| 252 to 253 | No recorder: stop here (logging only) |
| 254 to 259 | Save. `except Exception` is **deliberately broad**: accounting must **never break the request it is measuring**. If the database is down the call still succeeds; the failure is logged with `logger.exception` (full traceback) and the `request_id` |

A real log line from the run:
```json
{"level": "INFO", "logger": "ai_service.llm", "message": "llm stream ok: hosted gemini-3.1-flash-lite, 2881.1 ms",
 "request_id": "8f4475c6-...", "tenant_id": "e36a6991-...", "feature": "chat", "backend": "hosted",
 "model": "gemini-3.1-flash-lite", "operation": "stream", "status": "ok", "stop_reason": "stop",
 "input_tokens": 2939, "output_tokens": 114, "cache_read_tokens": 2030, "cache_write_tokens": 0,
 "cost_usd": "0.00095650", "latency_ms": 2881.1}
```

---

## Why the order of layers matters
`Retrying( Limited( Accounting( adapter ) ) )`: accounting is **inside** the retry layer. A request that fails twice and succeeds the third time makes **three rows** (`error`, `error`, `ok`), all with the same `request_id`. That is the honest cost picture (failed calls usually cost nothing, but the latency and the error type are exactly what you debug a flaky provider with). `tests/test_llm_accounting.py::test_every_retry_is_its_own_row` proves it.

## Tested in
`tests/test_llm_accounting.py` (13 tests): the cost sum, cache-write price, `None` for unknown usage or price, a success row, an error row, retries as rows, a finished stream, an abandoned stream (`cancelled`), a model with no price, a broken recorder that does not break the call, the log fields, and the real `DbCallRecorder` saving one row.

## Quick check
- Why is accounting placed closest to the provider?
- Why is `cost_usd` `None` and not 0 for an unknown model?
- When is a stream's status `cancelled` and when `ok`, if the consumer closes it?
- Why does `_finish` catch `Exception` broadly when saving?
- Why is the cost put in the log as a string?
