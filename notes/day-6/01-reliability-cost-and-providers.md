# Day 6: reliability, cost and provider abstraction

What was added to `ai-service` on Day 6, how the layers fit together, and what happened when I ran it against the real models. Decisions 25 to 36 are in `decisions.md`; the traps I hit are in `gotchas.md`.

## 1. The shape of the LLM layer
```
route  ->  FallbackClient            second backend, only for availability errors
              RetryingClient         back-off with jitter, obeys retry-after, time budget
                 LimitedClient       calls in flight + calls per minute
                    AccountingClient one log line and one llm_calls row per real call
                       adapter       OpenAICompatProvider / OllamaProvider / AnthropicProvider
```
Every box is an `LLMClient` (`generate`, `stream`, `generate_structured`), so the layers stack and each one can be tested alone with a scripted client.

| File | What it holds |
|---|---|
| `services/llm_types.py` | `LLMRequest`, `LLMResponse`, `Usage`, stream events, the `LLMClient` protocol, and the error types (`retryable`, `fallback_ok`) |
| `services/llm_openai.py` | Gemini, OpenAI and Ollama through the OpenAI SDK; maps its exceptions to my errors; normalises usage |
| `services/llm_anthropic.py` | Anthropic: system prompt apart, forced tool as the JSON schema, `cache_control`, its own usage names |
| `services/llm_wrappers.py` | `LimitedClient`, `RateLimiter`, `RetryingClient`, `FallbackClient` |
| `services/llm_accounting.py` | `AccountingClient`, `DbCallRecorder` |
| `services/llm_cost.py` | `compute_cost()` |
| `services/llm.py` | `SettingsLLMRegistry` builds the stack per backend from the settings; re-exports the types |
| `db/models/llm_call.py` + migration `86fde07d2bc3` | the `llm_calls` table |
| `prompts/chat_system.md` | the long, stable `/chat` system prompt (about 4.8K tokens) |
| `scripts/messy_inputs.py`, `scripts/run_messy_inputs.py` | the 50 inputs and the runner that reports on them |

## 2. Which errors are retried (task 3)
| Error (my type) | Source | Retry | Fallback |
|---|---|---|---|
| `RateLimitedError` | 429 | yes, waits `retry-after` | yes |
| `OverloadedError` | 5xx, 529, 408 | yes | yes |
| `LLMTimeoutError`, `LLMConnectionError` | no answer | yes | yes |
| `QuotaExhaustedError` | 429 with "per day" or `insufficient_quota` | no | yes |
| `AuthError`, `BadRequestError`, `ContextTooLongError` | 401, 403, 400, 404, 413 | no | no |
| refusal | HTTP 200, `stop_reason = content_filter` | not an error: `/extract` answers `422 EXTRACTION_REFUSED` | no |

A stream is retried or moved to the fallback only before its first text.

## 3. Cost and logs (task 2)
One log line per provider call (JSON; the formatter now carries these fields) and one `llm_calls` row:
```
llm stream ok: hosted gemini-3.1-flash-lite, 2881.1 ms
  request_id, tenant_id, user_id, feature=chat, backend=hosted, model=gemini-3.1-flash-lite,
  operation=stream, status=ok, input_tokens=2939, output_tokens=114, cache_read_tokens=2030,
  cache_write_tokens=0, cost_usd="0.00095650", latency_ms=2881.1
```
`cost = (new input x input price + output x output price + cache-read x cache-read price + cache-write x cache-write price) / 1,000,000`. The Gemini 3.1 Flash-Lite prices in `config.py` (0.25 input, 1.50 output, 0.025 cached input per million tokens) are from Google's pricing page; the free tier does not bill, so the number is what the paid tier would charge.

Cost per tenant and per feature is one query:
```sql
select feature, count(*) calls, sum(cost_usd) usd, sum(cache_read_tokens) cached
from llm_calls where tenant_id = '<tenant>' group by feature;
```

## 4. Prompt caching on `/chat` (task 7): real numbers
Four turns of one conversation, system prompt of about 4.8K tokens (Gemini 3.1 Flash-Lite, through the OpenAI-compatible endpoint):

| Turn | Prompt tokens | Cache read | Cost (USD) | Seconds |
|---|---|---|---|---|
| 1 | 4,839 | 0 | 0.00138525 | 3.7 |
| 2 | 4,969 | 2,030 | 0.00095650 | 2.9 |
| 3 | 5,096 | 2,028 | 0.00100670 | 3.5 |
| 4 | 5,230 | 2,025 | 0.00113238 | 3.0 |

From turn 2 about 40% of the prompt came from the cache and a turn cost about 30% less. The first attempt, with a 3.5K-token prompt, never hit the cache at all (0 on every turn); a prompt must be above the provider's minimum size, which the pricing page does not state for this model. `cache_read_tokens` is in the `done` event, the log line and the `llm_calls` row.

## 5. The 50 messy inputs (tasks 5 and 6)
The 50 inputs (`scripts/messy_inputs.py`) cover ordinary English, WhatsApp, Hinglish, Gujarati and Hindi script, four other languages, emojis, contradictions, greetings and noise, prompt injection, very long text, text over the 8,000-character limit, and empty text. `scripts/run_messy_inputs.py` sends them through `POST /extract` and sorts each answer into **valid**, **repaired**, **correctly refused**, **failed** (a handled error) or **unhandled** (must be 0), and also checks valid answers against what the text says.

| Run | valid | repaired | correctly refused | failed | unhandled | wrong field in a valid answer |
|---|---|---|---|---|---|---|
| hosted, schema only | 45 | 0 | 5 | 0 | 0 | 2 |
| local, schema only | 44 | 0 | 5 | 1 | 0 | **32** |
| hosted, with sanity checks | 44 | **1** | 5 | 0 | 0 | 2 |
| local, with sanity checks | 10 | 0 | 5 | **35** | 0 | 5 |

- **Done when: zero unhandled parse errors**: met in all four runs (0 of 50, and 0 in 113 model calls on the local run).
- With only the JSON schema, nothing ever needed a repair: the provider forces valid JSON, so the repair loop saw no real case. I added sanity checks to `Enquiry` that the schema cannot express (phone of 8 to 15 digits, a real-looking email, a budget between 0 and 10,000,000, a name of at most 60 characters). They are checked after the reply and are not sent to the model.
- **Hosted**: the checks caused one real repair (input 28: `budget_inr: -5000`, shown the error, answered `null`).
- **Local**: the 270M model could not repair a single answer, so 35 inputs became clean `422 EXTRACTION_FAILED` instead of nonsense in a valid shape.
- The report files are in `scripts/results/` (`messy_inputs_report_*.json`); `..._schema_only.json` are the first pass.
- The sanity checks cannot catch a believable invented value: the local model's `Alice`, `New York` and `555-1234-5678` for the message "Hi" pass them. Truth needs an evaluation set (Day 7+), not a validator.
- Full tables and the cost model are in `ai-eng-learning/day-6/Notes/tasks-1-7-reliability-cost-providers.md`.

## 6. Failure tests against the real provider
- **Fallback** (the hosted URL pointed at a closed port, `LLM_FALLBACK_BACKEND=local`): `/extract` and `/chat` each logged 3 failed tries (`LLMConnectionError`, back-off 0.3 to 0.9 s), then `llm fallback: hosted failed, trying local`, and answered from `gemma3:270m`. The response said so: `meta.backend = "local"`, `meta.fallback_used = true`; in `/chat` the `start` event and the saved message name `gemma3:270m`.
- **A real 429 burst**: 25 `/extract` requests at once against the free tier (15 per minute), no limiter. First run (backoff only, before reading Gemini's wait time): 19 answers and 6 `502`. After the fix that reads `Please retry in 12.1s.` from the error text: 25 of 25 answered, 6 rate-limit errors waited about 12 s each and one 503 was retried; 75 s in all.
- **The same burst before that found a different bug**: ten `500`s from the database pool (see `gotchas.md`), not from the model.

## 7. How to run it
```bash
# .env: LLM_API_KEY, LLM_MODEL, DATABASE_URL (see .env.example, Day 6 block)
uv run alembic upgrade head
uv run uvicorn ai_service.main:app --port 8010
uv run python scripts/run_messy_inputs.py --base-url http://localhost:8010   # needs DATABASE_URL for the cost totals
```
`LLM_REQUESTS_PER_MINUTE=12` keeps a batch under the free tier's 15 per minute. `LLM_FALLBACK_BACKEND=local` turns the fallback on.

## Quick check
- Which errors are retried, which fall back, and which are raised at once?
- Why is the accounting layer closest to the provider, and the retry layer outside it?
- What is the difference between `Usage.input_tokens` and `prompt_tokens`, and why does the adapter care?
- Why can a stream not be retried after its first word?
- What did the 25-request burst show about holding a database connection?
