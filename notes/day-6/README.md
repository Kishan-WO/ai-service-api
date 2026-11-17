# Day 6: reliability, cost and provider abstraction

**Build target (from the plan):** a production-shaped LLM layer that survives 50 messy inputs. **Done when** `/extract` survives all 50 with zero unhandled parse errors (met: 0 unhandled in every run). The concept notes (error handling, token accounting, prompt caching, provider abstraction) and the results with the cost table are in `ai-eng-learning/day-6/`.

## 1. The tasks, in the order of the plan

| Task | What the plan asked | Built in | Explained in |
|---|---|---|---|
| **1** | `LLMClient` protocol with two provider adapters plus an Ollama adapter, chosen through settings | `services/llm_types.py`, `llm_openai.py`, `llm_anthropic.py`, `llm.py` | explanation [01](explanation/01-llm_types.md), [03](explanation/03-llm_openai.md), [04](explanation/04-llm_anthropic.md), [07](explanation/07-llm_registry.md) |
| **2** | A wrapper that logs per request: model, input / output / cached tokens, cost, latency, request ID, tenant | `services/llm_accounting.py`, `llm_cost.py`, `db/models/llm_call.py` | explanation [02](explanation/02-config_and_llm_calls_table.md), [05](explanation/05-llm_accounting_and_cost.md) |
| **3** | Retry on transient errors with backoff; fall back to a second provider after N failures | `services/llm_wrappers.py` | explanation [06](explanation/06-llm_wrappers.md) |
| **4** | Retry-on-validation-failure loop for `/extract` (send the Pydantic error back, at most 2 retries) | `services/extract_service.py`, `schemas/extract.py` | explanation [08](explanation/08-extract_service_and_schema.md) |
| **5** | A file of 50 messy inputs | `scripts/messy_inputs.py` | explanation [11](explanation/11-messy_inputs_scripts.md) |
| **6** | Run all 50 through `/extract` and report: valid, repaired, correctly refused, failed | `scripts/run_messy_inputs.py` | explanation [11](explanation/11-messy_inputs_scripts.md) |
| **7** | Prompt caching on the `/chat` system prompt; show cache-read tokens in the logs | `prompts/chat_system.md`, `api/v1/chat.py`, `chat_service.py` | explanation [09](explanation/09-routes_chat_service_and_small_changes.md) |
| Notes | A cost model table | `ai-eng-learning/day-6/Notes/` | [01 overview](01-reliability-cost-and-providers.md), section "Cost" |
| (all) | Tests | `tests/test_llm_*.py` and more | explanation [10](explanation/10-tests.md) |

## 2. The implementation order (how it was built)

The folder [`explanation/`](explanation/README.md) is numbered in this order, so reading 01 to 11 follows the build:

| Step | What was built | File | Task |
|---|---|---|---|
| 1 | The shared types, `Usage` and the error family | [01-llm_types](explanation/01-llm_types.md) | 1, 3 |
| 2 | Settings (retry, limits, price table) and the `llm_calls` table | [02-config_and_llm_calls_table](explanation/02-config_and_llm_calls_table.md) | 2, 3 |
| 3 | The OpenAI-compatible adapter (Gemini, Ollama) | [03-llm_openai](explanation/03-llm_openai.md) | 1 |
| 4 | The Anthropic adapter | [04-llm_anthropic](explanation/04-llm_anthropic.md) | 1 |
| 5 | Accounting and cost | [05-llm_accounting_and_cost](explanation/05-llm_accounting_and_cost.md) | 2 |
| 6 | Limits, retry and fallback | [06-llm_wrappers](explanation/06-llm_wrappers.md) | 3 |
| 7 | The registry that builds the stack from settings | [07-llm_registry](explanation/07-llm_registry.md) | 1 |
| 8 | The `/extract` repair loop and sanity checks | [08-extract_service_and_schema](explanation/08-extract_service_and_schema.md) | 4 |
| 9 | The routes, prompt caching, small changes | [09-routes_chat_service_and_small_changes](explanation/09-routes_chat_service_and_small_changes.md) | 7 |
| 10 | The tests | [10-tests](explanation/10-tests.md) | all |
| 11 | The 50 inputs and the runner (live runs) | [11-messy_inputs_scripts](explanation/11-messy_inputs_scripts.md) | 5, 6 |

## 3. What is in this folder
| Item | Contents |
|---|---|
| [01-reliability-cost-and-providers.md](01-reliability-cost-and-providers.md) | the short overview: the layers, error table, cost, caching numbers, the 50-input results, how to run |
| [explanation/](explanation/README.md) | line-by-line explanation of every Day 6 file (11 files + index) |
| [questions/](questions/README.md) | every question I asked about Day 6 code (Q31 to Q42), in implementation order |

Reasons and traps: `decisions.md` items 25 to 38 and the Day 6 part of `gotchas.md` (project root).

Previous: [Day 5](../day-5/README.md).
