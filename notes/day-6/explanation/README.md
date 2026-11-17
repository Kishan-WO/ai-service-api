# Day 6 explained: every file, line by line

One markdown file per Day 6 file (or small group of files). **The numbers are the implementation order**: read 01 to 11 and you follow how the layer was built. The plan's tasks (1 to 7) are mapped to these files in [`../README.md`](../README.md).

| # | Explanation | Source it explains | What it covers |
|---|---|---|---|
| 1 | [01-llm_types.md](01-llm_types.md) | `services/llm_types.py` | The shared types, `Usage`, the error family (`retryable`, `fallback_ok`), the `LLMClient` protocol |
| 2 | [02-config_and_llm_calls_table.md](02-config_and_llm_calls_table.md) | `core/config.py`, `db/models/llm_call.py`, migration `86fde07d2bc3` | The new settings, the price table, the `llm_calls` table |
| 3 | [03-llm_openai.md](03-llm_openai.md) | `services/llm_openai.py` | Adapter for Gemini, OpenAI and Ollama; `map_openai_error`; usage normalising; Gemini's "retry in 23.6s" |
| 4 | [04-llm_anthropic.md](04-llm_anthropic.md) | `services/llm_anthropic.py` | Adapter for Anthropic: system apart, forced tool as schema, `cache_control` |
| 5 | [05-llm_accounting_and_cost.md](05-llm_accounting_and_cost.md) | `services/llm_accounting.py`, `services/llm_cost.py` | One log line and one row per call, the cost formula, cancelled streams |
| 6 | [06-llm_wrappers.md](06-llm_wrappers.md) | `services/llm_wrappers.py` | `RateLimiter`, `LimitedClient`, `RetryingClient` (backoff, jitter), `FallbackClient`, `_prime` |
| 7 | [07-llm_registry.md](07-llm_registry.md) | `services/llm.py` | `SettingsLLMRegistry`: building the stack from settings |
| 8 | [08-extract_service_and_schema.md](08-extract_service_and_schema.md) | `services/extract_service.py`, `schemas/extract.py`, `core/exceptions.py` | The repair loop and the sanity checks |
| 9 | [09-routes_chat_service_and_small_changes.md](09-routes_chat_service_and_small_changes.md) | `api/v1/extract.py`, `api/v1/chat.py`, `services/chat_service.py`, `prompts/chat_system.md`, `main.py`, `core/logging.py` | What changed in the routes, prompt caching, the connection give-back |
| 10 | [10-tests.md](10-tests.md) | `tests/test_llm_*.py`, `test_extract.py`, `test_chat.py`, `fakes.py` | What each test file proves |
| 11 | [11-messy_inputs_scripts.md](11-messy_inputs_scripts.md) | `scripts/messy_inputs.py`, `scripts/run_messy_inputs.py` | The 50 inputs and the runner |

## The whole of Day 6 in one picture
```
POST /extract or /chat
   |
   v  route (api/v1/*.py)           builds CallContext, gives the DB connection back, calls the registry
   |
   v  registry.get(backend)         services/llm.py
   |
   v  FallbackClient                second backend, only for availability errors
   v  RetryingClient                backoff + jitter, obeys retry-after, time budget
   v  LimitedClient                 N in flight, M per minute
   v  AccountingClient              one log line + one llm_calls row per real call (cost, tokens, latency)
   v  adapter                       OpenAICompatProvider / OllamaProvider / AnthropicProvider
   |
   v  provider (Gemini, Ollama, Anthropic)

/extract on top: extract_service  -> repair loop (max 2), refusal and cut-off handling, Pydantic sanity checks
/chat on top:    chat_service     -> long stable system prompt first (so the provider caches it)
```

## What Day 6 produced, in numbers
- 162 tests (73 on Day 5), strict mypy, ruff clean except one older line.
- **50 messy inputs**, 0 unhandled errors in all four runs. Gemini: 44 valid, 1 repaired, 5 correctly refused. Local 270M model: 10 valid, 35 handled failures, 5 refused.
- **Prompt caching** on `/chat`: about 40% of a 4.8K-token prompt came from the cache from turn 2; a turn cost about 30% less.
- **A 429 burst of 25 requests**: 25 of 25 answered after reading Gemini's wait time (12 s) from the error text.
- Bugs only the real runs found: the database pool emptied by slow model calls, Gemini's 429 with no `retry-after` header, a blank `.env` key counted as a real key, an emoji crashing the report.

## Related
- [`../01-reliability-cost-and-providers.md`](../01-reliability-cost-and-providers.md): the short overview.
- [`../questions/`](../questions/README.md): the questions I asked about this code.
- `decisions.md` items 25 to 38 and `gotchas.md` (Day 6 section) at the project root.
- `ai-eng-learning/day-6/learning/` (concepts) and `ai-eng-learning/day-6/Notes/` (results and the cost table).
