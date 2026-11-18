# Q45. How does `route()` work?

**What I asked:** "explain this function"

**Where it is:** `src/ai_service/services/router_service.py`, the function `route(...)`.

## The short answer
`route()` takes a user message and returns an answer plus timing and token details. It works in three steps.

**Step 1: rules first.** `_rule_based_intent(message)` checks regex rules ("charged twice", a whole-message "hi"). If one matches, the intent is known with no model call: `rule_matched=True` and the classify cost is 0.

**Step 2: the small model classifies** (only when no rule matched).
- It loads `classify_query` v5 and asks the small model for one label, with `max_tokens=20` because the reply is one word.
- If the classifier call fails with an `LLMError`, the code does not crash: `classify_resp` is set to `None` and the intent becomes `unclear`.
- `_parse_intent` turns the reply text into an intent (see Q46). A reply that is not a valid label also becomes `unclear`.
- The call context carries the prompt name and version, so the log row shows which prompt was used.

**Step 3: pick who answers and with which prompt.**

| Intent | Who answers | Prompt | Output cap |
|---|---|---|---|
| a known intent | the small model | `router_<intent>` v2 (a slice of the handbook) | `max_tokens=512` |
| `unclear` | the large model | `chat_system` v1 (the full handbook) | `large_max_tokens=2000` |

The cap is larger for the large model because a thinking model spends most of its output tokens on thinking. If the answer call fails, `route()` raises `LLMUnavailableError`, which the API turns into a clean 502.

**Return value.** A `RouterResult` with the answer, the intent, whether a rule matched, the model and backend that answered, the classify, answer and total latency in ms, and the token usage of both calls. The task 3 measurement reads these fields.

## Two details
- `time.perf_counter()` measures classify time and answer time separately, and total time for the whole function.
- `unclear` is the safe default everywhere: a rule miss, a classifier failure or a garbage label all send the request to the large model. Errors cost more money but never give a wrong specialised answer.
