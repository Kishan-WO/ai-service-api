# Settings and the `llm_calls` table

Two things that hold Day 6's **configuration** and **data**:
1. `src/ai_service/core/config.py`: the new settings (lines 14 to 21 and 55 to 102).
2. `src/ai_service/db/models/llm_call.py` (58 lines, new) and its migration `alembic/versions/86fde07d2bc3_llm_calls.py`.

Day 1 to 3 settings are explained in `notes/day-3/13-pydantic-settings-config.md`; only Day 6's changes are walked through here.

---

# Part 1: `core/config.py`

## Lines 14 to 20: `ModelPrice`
```python
class ModelPrice(BaseModel):
    input: float = Field(default=0.0, ge=0)
    output: float = Field(default=0.0, ge=0)
    cache_read: float = Field(default=0.0, ge=0)
    cache_write: float = Field(default=0.0, ge=0)
```
One row of the **price table**: USD per **1,000,000 tokens**, in four kinds. `ge=0` means "greater than or equal to 0": a negative price is rejected when settings load. All default to 0, so `ModelPrice()` means "a model with no per-token price" (the local one). It is a plain `BaseModel` (not `BaseSettings`) because it is **data inside a setting**, not a setting itself.

## Lines 55 to 70: the Day 5 LLM settings that were kept
`LLM_API_KEY` (a `SecretStr`: printing it shows `**********`), `LLM_BASE_URL`, `LLM_MODEL`, `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_OUTPUT_TOKENS`, `CHAT_SYSTEM_PROMPT`, `CHAT_HISTORY_LIMIT`. **Removed:** `LLM_MAX_RETRIES` (the SDK's own retry count). On Day 6 the SDK retry is off and my retry layer has its own settings.

## Lines 66 to 68: `CHAT_SYSTEM_PROMPT_FILE`
```python
CHAT_SYSTEM_PROMPT_FILE: str = ""
```
A path to a long system prompt file (relative to the project folder). When set it **replaces** `CHAT_SYSTEM_PROMPT`. A system prompt of 4,800 tokens does not fit nicely in an environment variable; a file does. Read by `chat_service.system_prompt()` (see `09-routes_chat_service_and_small_changes.md`). Empty by default so Day 5 behaviour is unchanged.

## Lines 72 to 77: the second provider and the fallback
| Setting | Meaning |
|---|---|
| `ANTHROPIC_API_KEY: SecretStr | None = None` | key for the Anthropic backend; `None` = not configured |
| `ANTHROPIC_MODEL: str = ""` | model name; empty = not configured |
| `LLM_FALLBACK_BACKEND: Literal["hosted","local","anthropic"] | None = None` | which backend answers when the requested one keeps failing. `None` = no fallback. `Literal` means a typo like `"locl"` fails at start-up, not at 3 a.m. |

## Lines 78 to 81: the retry policy
| Setting | Default | Used as |
|---|---|---|
| `LLM_RETRY_ATTEMPTS` | 3 (`ge=1`) | tries per backend, the first included |
| `LLM_RETRY_BASE_DELAY_SECONDS` | 1.0 | the first backoff ceiling; doubles each attempt |
| `LLM_RETRY_MAX_DELAY_SECONDS` | 20.0 | the cap on the ceiling |
| `LLM_RETRY_TOTAL_SECONDS` | 90.0 (`gt=0`) | stop retrying when the next wait would pass this |

`RetryPolicy.from_settings` (in `llm_wrappers.py`) reads exactly these four.

## Lines 82 to 85: the limits
| Setting | Default | Meaning |
|---|---|---|
| `LLM_MAX_CONCURRENCY` | 4 (`ge=1`) | calls in flight at once, per backend (the semaphore) |
| `LLM_REQUESTS_PER_MINUTE` | 0 (`ge=0`) | calls per minute for `hosted`; **0 = no limit**. Set about 12 for the Gemini free tier (limit 15) |

## Lines 87 to 96: `LLM_PRICES`, the price table
```python
LLM_PRICES: dict[str, ModelPrice] = Field(
    default_factory=lambda: {
        "gemini-3.1-flash-lite": ModelPrice(input=0.25, output=1.50, cache_read=0.025),
        "gemma3:270m": ModelPrice(),
    }
)
```
- A **dictionary from model name to price**. Keyed by the model that answered, so a fallback to another model is priced correctly.
- `default_factory` with a lambda builds a **new dict for each Settings object** (mutable defaults must never be shared).
- The Gemini numbers come from Google's pricing page (standard tier, checked 2026-11). Comment (line 92): the free tier does not bill, so this is the cost a paid key would have.
- Because it is a Pydantic setting, it can be overridden from the environment with JSON: `LLM_PRICES='{"gemini-3.1-flash-lite": {"input": 0.25, "output": 1.5, "cache_read": 0.025}}'`. That is what "prices live in config" means: no code change when a provider changes its price.
- A model that is **not** in the table gets `cost = None` in the log and the row; it never breaks a request.

## Lines 98 to 102: `blank_means_not_set` (a real bug found)
```python
@field_validator("LLM_API_KEY", "ANTHROPIC_API_KEY", "LLM_FALLBACK_BACKEND", mode="before")
@classmethod
def blank_means_not_set(cls, v: object) -> object:
    return None if isinstance(v, str) and not v.strip() else v
```
`.env.example` ships `LLM_API_KEY=` (empty). A `.env` line `KEY=` arrives as the empty **string**, and `SecretStr("")` is **not** `None`: the hosted backend looked configured and failed later with a 401. This validator turns a blank string into `None` **before** type checking (`mode="before"`). `LLM_FALLBACK_BACKEND=` empty would otherwise crash start-up (`""` is not a valid `Literal`). `@classmethod` is required by pydantic for validators; `cls` is unused. Tested in `tests/test_llm_registry.py::test_a_blank_value_in_the_env_file_means_not_set`.

---

# Part 2: `db/models/llm_call.py`

One row per **provider call** (not per user message): a retry, a fallback call and each repair attempt are their own rows, all sharing a `request_id`. Cost questions become one `GROUP BY`.

## Lines 1 to 17: header
Docstring; imports (the column types and `Index`); `_ID = BigInteger().with_variant(Integer, "sqlite")`: PostgreSQL gets a `BIGINT`, SQLite (the test database) gets `INTEGER`, because SQLite only auto-increments an `INTEGER` primary key. Same trick as `messages.id` on Day 5.

## Lines 19 to 22: the status constants
`CALL_OK = "ok"`, `CALL_ERROR = "error"`, `CALL_CANCELLED = "cancelled"`. Strings in a `String(16)` column instead of a database enum: adding a status needs no migration.

## Lines 25 to 52: the columns
| Line | Column | Meaning |
|---|---|---|
| 25 | `class LLMCall(Base, TimestampMixin)` | gets `created_at` and `updated_at` from the mixin |
| 28 | `id` | the primary key, auto-incrementing |
| 29 | `request_id` | `String(64)`, nullable, **indexed**: groups every call of one HTTP request (the `X-Request-ID`) |
| 31 to 36 | `tenant_id`, `user_id` | nullable foreign keys with `ondelete="SET NULL"`. **Not `CASCADE`** (which Day 5's tables use): if a tenant is deleted its cost history must stay (an accounting record), so the link is just cleared. Nullable also lets a script run with no tenant |
| 37 | `feature` | which part of the product: `chat`, `extract` |
| 38 to 39 | `backend`, `model` | what answered |
| 40 to 42 | `operation` | `generate`, `stream` or `structured` (the formatter split the line into three; it is one column) |
| 43 | `status` | `ok`, `error` or `cancelled` |
| 44 | `error_type` | the error class name when `status = error` |
| 45 | `stop_reason` | `stop`, `length`, `content_filter` |
| 46 | comment | **NULL means "the provider did not say", which is not the same as 0** |
| 47 to 50 | the four token columns | nullable ints |
| 51 | `cost_usd` | `Numeric(14, 8)`: up to 14 digits, 8 after the point. `Decimal` in Python, exact in PostgreSQL |
| 52 | `latency_ms` | `Float`, required |

## Lines 54 to 57: two composite indexes
```python
Index("ix_llm_calls_tenant_id_created_at", "tenant_id", "created_at"),
Index("ix_llm_calls_feature_created_at", "feature", "created_at"),
```
Shaped for the two real questions: "what did **this tenant** spend in this period" and "what did **this feature** spend". The leading column is the filter, the second is the time range. (Same reasoning as the `messages` index in `../../day-5/questions/09-my-questions-while-reading-the-code.md`.) Naming the indexes explicitly keeps Alembic's autogenerate stable.

---

# Part 3: the migration `86fde07d2bc3_llm_calls.py`
Created with `alembic revision --autogenerate -m "llm_calls"` against the `day6-llm-reliability` database.
- `upgrade()` creates the table with all columns, both foreign keys (named by the project's naming convention, e.g. `fk_llm_calls_tenant_id_tenants`) and three indexes.
- `downgrade()` drops the indexes, then the table.
- `down_revision = 'c2b3d69c8756'`: it comes after the Day 5 migration.
- Tested on PostgreSQL: `upgrade head`, `downgrade -1`, `upgrade head`, then `alembic check` printed "No new upgrade operations detected."
- **Exported** in `db/models/__init__.py` (`LLMCall` added to `__all__`), which is what `alembic/env.py` imports so autogenerate can see the model.

Useful query on this table:
```sql
select feature, backend, status, count(*) calls, round(sum(cost_usd)::numeric, 6) usd
from llm_calls group by 1, 2, 3 order by 1, 2, 3;
```

## Quick check
- Why is `LLM_PRICES` a dict by model name and not one price?
- Why `SET NULL` and not `CASCADE` on `llm_calls.tenant_id`?
- Why does `blank_means_not_set` use `mode="before"`?
- What is the difference between `cost_usd = NULL` and `cost_usd = 0.00000000`?
