# Q48. `router_graph.py` explained line by line

**What I asked:** "explain router_graph.py file line by line" (then "go line by line in steps")

**File:** `src/ai_service/services/router_graph.py` (229 lines). It is the same router as `route()` in `router_service.py`, built as a LangGraph graph (Day 8, task 5). Only the orchestration is different: the steps are nodes, and "what comes next" is an edge.

I went through it in 12 steps, in file order. The line numbers are the numbers in the file.

| Step | Lines | What |
|---|---|---|
| 1 | 1–18 | the docstring and the standard imports |
| 2 | 20–21 | the LangGraph imports |
| 3 | 23–45 | my own imports |
| 4 | 47–62 | the logger and the state |
| 5 | 65–85 | `RouterDeps` and `_ctx` |
| 6 | 88–92 | the `rules` node |
| 7 | 95–117 | the `classify` node |
| 8 | 120–149 | the `_answer` helper |
| 9 | 152–165 | the `answer_known` and `answer_large` nodes |
| 10 | 168–174 | the two edge functions |
| 11 | 177–189 | `build_router_graph` |
| 12 | 192–229 | the compiled graph and the entry point |

---

## Step 1: lines 1–18 (the docstring and the standard imports)

**Lines 1–14: the module docstring.** It has no effect on how the code runs. It is documentation, and it says four things:

- This is the same router as `route()`, built as a LangGraph graph.
- Only the orchestration differs. The steps become nodes, and "what comes next" becomes an edge.
- The ASCII drawing shows the flow: `rules`, then either `classify` or a direct jump, then `answer_known` or `answer_large`, then `END`.
- The models are my own `LLMClient`, not LangChain objects. So LangGraph adds no prompt and no extra call, and `tests/test_router_graph.py` checks that.

**Lines 15–18: the standard-library imports.**

```python
import logging
import time
from dataclasses import dataclass
from typing import Any, TypedDict
```

| Line | Import | Used for |
|---|---|---|
| 15 | `logging` | `logger.warning(...)` when the classifier or answer call fails (lines 108 and 141) |
| 16 | `time` | `time.perf_counter()` to measure classify, answer and total latency |
| 17 | `dataclass` | the `RouterDeps` class (line 65), a plain holder for the clients and caps |
| 18 | `Any` | a type that means "anything". It is used for `prompt`, `checkpointer` and similar values that don't need a precise type. |
| 18 | `TypedDict` | the `RouterState` class (line 50). It is a dict with fixed, named keys that a type checker understands. |

Nothing here is specific to LangGraph. The LangGraph imports start on line 20.

---

## Step 2: lines 20–21 (the LangGraph imports)

```python
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
```

These are the only two lines in the file that import LangGraph. Everything else is my own code.

**Line 20: three names from `langgraph.graph`**

| Name | What it is | Where it is used |
|---|---|---|
| `StateGraph` | A class that I add nodes and edges to. It is the builder, not the finished graph. | Line 179: `StateGraph(RouterState, context_schema=RouterDeps)` |
| `START` | A marker for "the graph begins here". It is not a node, so it runs no code. | Line 184: `add_edge(START, "rules")` |
| `END` | A marker for "the graph finishes here". | Lines 187–188: `add_edge("answer_known", END)` |

**Line 21: `Runtime`**
- This is a type that a node can ask for as a second parameter. LangGraph passes the run's context through it.
- In my code the context is a `RouterDeps` object, which holds the clients and token caps.
- It is used in `classify`, `answer_known` and `answer_large`:
  ```python
  async def classify(state: RouterState, runtime: Runtime[RouterDeps]) -> RouterState:
      deps = runtime.context
  ```
- `Runtime[RouterDeps]` is only a type hint, so type checkers know `runtime.context` is a `RouterDeps`.
- LangGraph looks at that second parameter and fills it in when it runs the node. Nodes that don't ask for it, like `rules`, don't get it.

**Why use `Runtime` at all**
- The graph is compiled once, on line 192, when the module loads.
- The clients are different for each request. They can't be stored inside the compiled graph.
- `Runtime` is how per-request objects reach the nodes without being put in the state.

---

## Step 3: lines 23–45 (my own imports)

These imports come from this project, not from a library.

```python
from ai_service.core.exceptions import LLMUnavailableError
```

**Line 23.** `LLMUnavailableError` is the clean "could not reach the model" error. It is raised in `_answer` (line 142), and the API turns it into a 502. Because the plain router raises the same error, the two flows fail the same way.

```python
from ai_service.services.llm_types import (
    CallContext, ChatMessage, LLMClient, LLMError, LLMRequest, Usage,
)
```

**Lines 24–31.** These are the types used to talk to a model:

| Name | Used for |
|---|---|
| `CallContext` | the log metadata for one call (request id, tenant, feature, prompt name and version) |
| `ChatMessage` | one message, as `ChatMessage("user", text)` |
| `LLMClient` | the type of the clients. It is an interface, so any model client fits. |
| `LLMError` | the error that a failed model call raises. The `except LLMError` blocks catch it. |
| `LLMRequest` | the request: messages, `max_tokens` and the context |
| `Usage` | token counts. It is only used as a type in `RouterState`. |

```python
from ai_service.services.prompt_registry import get_prompt
```

**Line 32.** `get_prompt(name, version)` loads a prompt file such as `prompts/classify_query/v5.md`. The prompt text stays out of the code.

```python
from ai_service.services.router_service import (
    _CLASSIFIER_PROMPT_NAME, _CLASSIFIER_PROMPT_VERSION,
    _GENERAL_PROMPT_NAME, _GENERAL_PROMPT_VERSION,
    _PROMPT_NAME, _PROMPT_VERSION,
    KNOWN_INTENTS, Intent, RouterResult,
    _parse_intent, _rule_based_intent,
)
```

**Lines 33–45.** This is the reuse from the plain router. I did not copy these pieces into the graph file.

| Names | What they are |
|---|---|
| `_CLASSIFIER_PROMPT_NAME` and `_VERSION` | `classify_query` and `v5` |
| `_GENERAL_PROMPT_NAME` and `_VERSION` | `chat_system` and `v1`, used when the intent is unclear |
| `_PROMPT_NAME` and `_PROMPT_VERSION` | the `router_<intent>` names and `v2`, used for known intents |
| `KNOWN_INTENTS` | the set of the six known labels. `unclear` is not in it. |
| `Intent` | the type of an intent label |
| `RouterResult` | the result shape that `route()` returns |
| `_parse_intent` | turns the classifier's reply into a label |
| `_rule_based_intent` | the free regex rules |

**Why share them**
- The graph and the plain flow use the same prompts, the same rules and the same parser.
- The only difference between them is how the steps are wired together.
- That is why the comparison in `tests/test_router_graph.py` means something. If the graph used its own copies, a difference in output could come from a prompt change and not from the framework.
- The leading underscore marks these names as private to `router_service.py`. I import them anyway because both files are in the same package.

---

## Step 4: lines 47–62 (the logger and the state)

```python
logger = logging.getLogger("ai_service.router_graph")
```

**Line 47.** This creates a logger named `ai_service.router_graph`. The two `logger.warning(...)` calls in this file use it (lines 108 and 141). The name shows up in log lines, so I can tell the graph's messages from the plain router's.

```python
class RouterState(TypedDict, total=False):
    """Everything the flow knows. Each node returns only the keys it changes."""

    message: str
    intent: Intent
    rule_matched: bool
    classify_latency_ms: float
    classify_usage: Usage | None
    answer: str
    answer_model: str
    answer_backend: str
    answer_latency_ms: float
    answer_usage: Usage | None
```

**Line 50: the declaration.**
- `RouterState` is a `TypedDict`: a normal dict whose keys and value types are fixed.
- `total=False` means a key does not have to be present. This matters because the state grows as the graph runs.

**What the state holds at each point**

| Key | Set by | Meaning |
|---|---|---|
| `message` | the caller, at the start | the user's text |
| `intent` | `rules` or `classify` | the decided label, including `unclear` |
| `rule_matched` | `rules` | `True` if a regex decided and no model call was used |
| `classify_latency_ms` | `rules` (as 0) or `classify` | time for the classification step |
| `classify_usage` | `classify` | tokens used by the classifier call. It is `None` or absent on a rule path. |
| `answer` | `answer_known` or `answer_large` | the reply text |
| `answer_model` | the same | which model answered |
| `answer_backend` | the same | which backend answered |
| `answer_latency_ms` | the same | time for the answer call |
| `answer_usage` | the same | tokens used by the answer call |

**How the state changes during a run**
- It starts as `{"message": "How much is the course?"}`.
- After `rules`: `{"message": ..., "rule_matched": False}`.
- After `classify`: it also has `intent: "fees"`, `classify_usage` and `classify_latency_ms`.
- After `answer_known`: it also has `answer`, `answer_model`, `answer_backend`, `answer_usage` and `answer_latency_ms`.
- At the end, `result_from_state` (line 195) turns this dict into a `RouterResult`.

**The key rule: a node returns only what it changes.**
- A node does not return the whole state. For example, `rules` returns `{"rule_matched": False}`.
- LangGraph merges that small dict into the state.
- Because no node returns the whole state, one node cannot overwrite what another node set.

**Two details**
- The `Usage | None` types exist because there is no classifier usage when a rule decides. The classifier can also fail before it returns usage.
- Because `intent` can be missing, `after_rules` (line 170) uses `"intent" in state` as its test. A missing `intent` key is the signal that no rule matched.

---

## Step 5: lines 65–85 (`RouterDeps` and `_ctx`)

```python
@dataclass(frozen=True)
class RouterDeps:
    """What the nodes need besides the state: passed per call, so one compiled graph serves all."""

    small_client: LLMClient
    large_client: LLMClient
    context: CallContext
    max_tokens: int = 512
    large_max_tokens: int = 2000
```

**Line 65: `@dataclass(frozen=True)`**
- `@dataclass` writes the `__init__` for me. `RouterDeps(small, large, ctx, 512, 2000)` works without any extra code.
- `frozen=True` means the object can't be changed after it is created. A node can't change the clients by accident.

**Lines 69–73: the five fields**

| Field | Meaning |
|---|---|
| `small_client` | the cheap model. It classifies and answers known intents. |
| `large_client` | the capable model. It answers only when the intent is `unclear`. |
| `context` | the caller's `CallContext`, with the request, tenant and user ids |
| `max_tokens` | the answer cap for the small model (default 512) |
| `large_max_tokens` | the answer cap for the large model (default 2000) |

**Why these are not in `RouterState`**
- The state holds data that the flow produces and changes: the intent, the answer, the latencies.
- `RouterDeps` holds tools and settings that stay the same for the whole run. It holds clients and caps, not results.
- The graph is compiled once at import (line 192). The clients differ per request, so they can't be built into the graph.
- They travel in as the run's context instead. Line 228 passes them with `ainvoke(..., context=deps)`, and nodes read them with `runtime.context`.

```python
def _ctx(deps: RouterDeps, feature: str, prompt: Any) -> CallContext:
    c = deps.context
    return CallContext(
        request_id=c.request_id,
        tenant_id=c.tenant_id,
        user_id=c.user_id,
        feature=feature,
        prompt_name=prompt.name,
        prompt_version=prompt.version,
    )
```

**Line 76: the signature**
- `_ctx` builds the `CallContext` for one model call. The leading underscore means it is a private helper.
- It takes the deps, a `feature` name and the prompt object. `prompt` is typed `Any`, though it is really a `Prompt` from the registry.

**Line 77.** `c` is the caller's context, passed down from the API. It carries who is asking.

**Lines 78–85: a new context.**
- It copies `request_id`, `tenant_id` and `user_id` unchanged, so every call is tied to the same request and user.
- It sets `feature` to something specific, such as `router_classify` or `router_answer_fees`. This is what separates the classify call from the answer call in the `llm_calls` table.
- It sets `prompt_name` and `prompt_version` from the prompt file that was used, so each call row shows which prompt version produced it.

**How it is used**
- `classify` calls `_ctx(deps, "router_classify", prompt)` (line 104).
- `_answer` calls `_ctx(deps, feature, prompt)` (line 137).
- This is the same context-building the plain router writes out inline three times. In the graph file I wrote it once as a helper.

---

## Step 6: lines 88–92 (the `rules` node)

```python
async def rules(state: RouterState) -> RouterState:
    intent = _rule_based_intent(state["message"])
    if intent is None:
        return {"rule_matched": False}
    return {"intent": intent, "rule_matched": True, "classify_latency_ms": 0.0}
```

**Line 88: the signature**
- This is a graph node: a function that takes the current state and returns a dict of changes to it.
- It is `async` because LangGraph's `ainvoke` runs nodes as coroutines. It has no `await` inside, since the rule check is instant.
- It takes only `state`. It does not ask for `runtime`, because it needs no clients.
- `-> RouterState` means the returned dict uses keys from the state class. It is a partial dict, not the whole state.

**Line 89: run the regex rules**
- `_rule_based_intent` is the function imported from the plain router. It checks the message against the regexes for "charged twice", "no access", "refund policy", and a whole-message greeting.
- It returns an intent label such as `"complaint"`, or `None` if no rule matched.
- This costs no model call and takes no noticeable time.

**Lines 90–91: no rule matched**
- It returns only `{"rule_matched": False}`.
- It does not set `intent`. An absent `intent` key is the signal that the model must decide.
- `after_rules` (line 168) reads that signal and sends the flow to `classify`.

**Line 92: a rule matched**
- It sets three keys: the `intent`, `rule_matched=True`, and `classify_latency_ms=0.0`.
- Setting the classify latency to 0 matters later. `result_from_state` reads it, and a rule path has no classification time.
- It sets no `classify_usage`, because no model was called. That is why `classify_usage` can be missing from the state.

**Two examples**

| Message | What `rules` returns |
|---|---|
| "I was charged twice" | `{"intent": "complaint", "rule_matched": True, "classify_latency_ms": 0.0}` |
| "How much is the course?" | `{"rule_matched": False}` |

In the first case the flow skips `classify` and goes to `answer_known`, which makes only one model call. In the second case the small model classifies the message next.

---

## Step 7: lines 95–117 (the `classify` node)

```python
async def classify(state: RouterState, runtime: Runtime[RouterDeps]) -> RouterState:
    deps = runtime.context
    prompt = get_prompt(_CLASSIFIER_PROMPT_NAME, _CLASSIFIER_PROMPT_VERSION)
    started = time.perf_counter()
```

**Line 95: the signature**
- This node has a second parameter, `runtime`. LangGraph sees it and fills it in with the run's context.
- `Runtime[RouterDeps]` is only a type hint, so type checkers know what `runtime.context` is.

**Line 96.** `deps = runtime.context` gets the `RouterDeps` object that `route_with_graph` passed in. It holds the clients and token caps.

**Line 97.** `get_prompt("classify_query", "v5")` loads the classifier prompt from the registry. The result is cached, so repeat loads are cheap.

**Line 98.** `time.perf_counter()` starts a stopwatch. It is used for the classify latency at the end.

```python
    try:
        response = await deps.small_client.generate(
            LLMRequest(
                messages=[ChatMessage("user", prompt.render(message=state["message"]))],
                max_tokens=20,
                context=_ctx(deps, "router_classify", prompt),
            )
        )
```

**Lines 99–106: the model call**
- It uses the small model: `deps.small_client`.
- The request has one user message. `prompt.render(message=...)` fills the user's text into the `{{ message }}` slot of the prompt.
- `max_tokens=20` is enough because the reply is a single label.
- `_ctx(...)` builds the log context with `feature="router_classify"` and the prompt's name and version.
- The call goes through my layered client, so retry, rate limits and cost logging apply. LangGraph is not involved in the call itself.

```python
    except LLMError as exc:
        logger.warning("router graph: classifier failed (%s); using unclear", exc.kind)
        return {
            "intent": "unclear",
            "classify_latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
```

**Lines 107–112: the classifier failed**
- It catches only `LLMError`, which is a provider failure such as a timeout or 503. A bug is not caught here, so it is not hidden.
- It logs a warning with the error kind, such as `OverloadedError`.
- It returns `intent: "unclear"`, so the request goes to the large model. A failed classifier does not fail the request.
- It still reports the time spent. It sets no `classify_usage`, since no usage came back.

```python
    return {
        "intent": _parse_intent(response.text),
        "classify_usage": response.usage,
        "classify_latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }
```

**Lines 113–117: success**
- `_parse_intent(response.text)` turns the reply into one of the six known labels, or `unclear` if the reply is not a valid label.
- `classify_usage` stores the token counts, which the cost measurement reads.
- `classify_latency_ms` is the elapsed time in milliseconds, rounded to one decimal place.

**What this node does not decide:** it only writes the intent into the state. The choice of the next node is made by `after_classify` (line 173), which reads `state["intent"]`.

---

## Step 8: lines 120–149 (the `_answer` helper)

```python
async def _answer(
    state: RouterState,
    client: LLMClient,
    prompt: Any,
    feature: str,
    max_tokens: int,
    deps: RouterDeps,
) -> RouterState:
    started = time.perf_counter()
```

**Lines 120–127: the signature**
- `_answer` is not a node. It has a leading underscore and is never registered with the graph. It is a plain helper that two nodes call.
- It makes the answer call for both paths. The caller supplies the parts that differ:

| Parameter | Meaning |
|---|---|
| `state` | the current state, which supplies the user's message |
| `client` | which model answers: the small one or the large one |
| `prompt` | the system prompt: the intent's slice or the full handbook |
| `feature` | the name written to the log, such as `router_answer_fees` |
| `max_tokens` | the answer cap: 512 or 2000 |
| `deps` | the run's context, which `_ctx` needs |

**Line 128.** Start the stopwatch.

```python
    try:
        response = await client.generate(
            LLMRequest(
                messages=[
                    ChatMessage("system", prompt.render()),
                    ChatMessage("user", state["message"]),
                ],
                max_tokens=max_tokens,
                context=_ctx(deps, feature, prompt),
            )
        )
```

**Lines 129–139: the model call**
- The request has two messages. The system message is the rendered prompt, and the user message is the original text.
- `prompt.render()` takes no variables. The answer prompts are handbook text with no `{{ }}` slots.
- `max_tokens` is the cap the caller chose. `_ctx` builds the log context.
- This is the same request shape as in the plain router. The comparison test checks that the two flows send identical requests.

```python
    except LLMError as exc:
        logger.warning("router graph: the answer call failed (%s)", exc.kind)
        raise LLMUnavailableError() from exc
```

**Lines 140–142: the call failed**
- Unlike `classify`, there is no safe fallback here, so the error is raised.
- It logs the error kind, then raises `LLMUnavailableError`. The original error is chained with `from exc`, so the log keeps the real cause.
- The API turns this error into a clean 502 response. The user never sees the provider's raw error.
- LangGraph lets this exception out of `ainvoke` with a note added: `During task with name 'answer_known'`.

```python
    return {
        "answer": response.text,
        "answer_model": response.model,
        "answer_backend": response.backend,
        "answer_usage": response.usage,
        "answer_latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }
```

**Lines 143–149: success.** It returns five keys for the state:
- the answer text;
- the model name and backend that answered, which can differ from what was asked for if a fallback ran;
- the token usage, which the cost measurement reads;
- the latency in ms.

**Why one helper:** the plain router writes this call out in one function with an `if` for the two cases. Here the graph has two nodes, and the shared helper keeps the call code in one place.

---

## Step 9: lines 152–165 (the `answer_known` and `answer_large` nodes)

```python
async def answer_known(state: RouterState, runtime: Runtime[RouterDeps]) -> RouterState:
    deps = runtime.context
    prompt = get_prompt(_PROMPT_NAME[state["intent"]], _PROMPT_VERSION)
    return await _answer(
        state, deps.small_client, prompt, f"router_answer_{state['intent']}", deps.max_tokens, deps
    )
```

**`answer_known` (lines 152–157)**: the cheap path, for a known intent.
- **Line 153:** read the run's context to get the clients and caps.
- **Line 154:** pick the prompt for this intent.
  - `_PROMPT_NAME` is the dict `{"fees": "router_fees", ...}` from the plain router.
  - With version `v2`, the fees intent loads `router_fees/v2.md`, which is only the fees slice of the handbook.
- **Lines 155–157:** call `_answer` with these choices:
  - the small client;
  - the feature name `router_answer_<intent>`, such as `router_answer_fees`;
  - the small model's cap of 512 tokens.

```python
async def answer_large(state: RouterState, runtime: Runtime[RouterDeps]) -> RouterState:
    deps = runtime.context
    prompt = get_prompt(_GENERAL_PROMPT_NAME, _GENERAL_PROMPT_VERSION)
    return await _answer(
        state, deps.large_client, prompt, "router_answer_unclear", deps.large_max_tokens, deps
    )
```

**`answer_large` (lines 160–165)**: the escalation path, for an unclear request.
- **Line 162:** the prompt is `chat_system` v1, the full handbook. There is no intent to pick a slice from.
- **Lines 163–165:** call `_answer` with these choices:
  - the large client;
  - the feature name `router_answer_unclear`;
  - the larger cap, `large_max_tokens`, which is 2000.

**The differences between the two nodes**

| | `answer_known` | `answer_large` |
|---|---|---|
| Model | small (`small_client`) | large (`large_client`) |
| Prompt | `router_<intent>` v2, a slice (3.7K to 13K characters) | `chat_system` v1, the full handbook (20.4K characters) |
| Cap | 512 tokens | 2000 tokens |
| Log feature | `router_answer_<intent>` | `router_answer_unclear` |

**Why 2000 for the large model:** a thinking model spends most of its output budget on thinking. In the task 3 measurement a 1,000-token cap was used up by thinking, and an answer stopped mid-sentence.

**Why two nodes and not one:** in a graph, each branch is a named node that can be drawn, streamed and paused. This is why the pause and resume test can say `interrupt_before=["answer_large"]`. It stops only the expensive path and lets the cheap path run.

**What they have in common:** both are thin. They pick the client, the prompt and the cap, then hand the work to `_answer`. Neither contains any model-call code of its own.

---

## Step 10: lines 168–174 (the two edge functions)

```python
def after_rules(state: RouterState) -> str:
    """A rule already decided: go to the answer. Otherwise ask the small model."""
    return after_classify(state) if "intent" in state else "classify"


def after_classify(state: RouterState) -> str:
    return "answer_known" if state["intent"] in KNOWN_INTENTS else "answer_large"
```

**What these are.** Edge functions are not nodes. They do no work and call no model. Each one reads the state and returns the name of the next node as a string. LangGraph runs one right after a node finishes and then moves to the node it names.

**`after_rules` (lines 168–170)** runs after the `rules` node, so there are two cases.
- **`"intent" in state` is true:** a rule matched and set the intent. The model is not needed, so it asks `after_classify` which answer node to use. It returns `"answer_known"` or `"answer_large"`. In practice every rule intent is a known one, so it goes to `answer_known`.
- **`"intent"` is missing:** no rule matched, so it returns `"classify"` and the small model decides.
- The test is whether the key exists. That is why `rules` leaves `intent` out when nothing matched (step 6).

**`after_classify` (lines 173–174)** runs after the `classify` node.
- If `state["intent"]` is one of the six known labels, it returns `"answer_known"`.
- Otherwise the intent is `unclear`, so it returns `"answer_large"`.
- It reads `KNOWN_INTENTS`, which does not contain `unclear`.
- A classifier failure sets `unclear`, and a garbage label parses to `unclear`. Both go to the large model.

**Why `after_rules` calls `after_classify`:** a rule match and a classifier result both end up as an `intent` in the state, and both need the same decision. Reusing the function keeps that rule in one place.

**Examples**

| State when the edge function runs | Returns |
|---|---|
| after `rules`, `{"rule_matched": False}` | `"classify"` |
| after `rules`, `{"intent": "complaint", ...}` | `"answer_known"` |
| after `classify`, `intent = "fees"` | `"answer_known"` |
| after `classify`, `intent = "unclear"` | `"answer_large"` |

**Compare with the plain router.** `route()` has the same decisions as `if` statements written inline. The graph pulls each one out into a named function, which makes it visible in the diagram and easy to test alone. The cost is that the flow is spread over several small functions and no longer reads top to bottom.

---

## Step 11: lines 177–189 (`build_router_graph`)

```python
def build_router_graph(*, checkpointer: Any = None, interrupt_before: list[str] | None = None):  # type: ignore[no-untyped-def]
    """Compile the graph once; pass `RouterDeps` as the run's context on every call."""
```

**Line 177: the signature**
- `*` means both parameters must be passed by name.
- `checkpointer` is where the graph saves its state after each step. It is `None` by default, so there is no saving. It is only used in the pause and resume test.
- `interrupt_before` is a list of node names to pause before. It is `None` by default, so there is no pause.
- The `# type: ignore[no-untyped-def]` comment is there because I left off the return type. The compiled graph's type is long and generic, and I did not write it out.

```python
    graph = StateGraph(RouterState, context_schema=RouterDeps)
```

**Line 179: the builder**
- `RouterState` tells LangGraph what keys the shared state has.
- `context_schema=RouterDeps` tells it what the per-run context looks like. This is what lets `Runtime[RouterDeps]` work in the nodes.

```python
    graph.add_node("rules", rules)
    graph.add_node("classify", classify)
    graph.add_node("answer_known", answer_known)
    graph.add_node("answer_large", answer_large)
```

**Lines 180–183: the nodes.** Each call gives a name and the function to run. The names are what the edges and the diagram use, and what streamed updates report.

```python
    graph.add_edge(START, "rules")
```

**Line 184: the entry point.** A plain edge. Every run starts at `rules`.

```python
    graph.add_conditional_edges("rules", after_rules, ["classify", "answer_known", "answer_large"])
    graph.add_conditional_edges("classify", after_classify, ["answer_known", "answer_large"])
```

**Lines 185–186: the branches**
- `add_conditional_edges(source, chooser, possible_targets)` means: after `source` finishes, call `chooser(state)` and go to the node it names.
- The third argument lists the nodes the chooser might return. LangGraph does not need it to run, but without it the drawing can't show the branches.
- After `rules` there are three possible targets. After `classify` there are two, because the classifier never sends the flow back to itself.

```python
    graph.add_edge("answer_known", END)
    graph.add_edge("answer_large", END)
```

**Lines 187–188: the exits.** Both answer nodes finish the run.

```python
    return graph.compile(checkpointer=checkpointer, interrupt_before=interrupt_before)
```

**Line 189: compile**
- Up to here `graph` is only a description. `compile()` checks it and turns it into a runnable object.
- If a node name is wrong or a node can't be reached, compile raises an error. The mistake shows up at import, not when a user's request arrives.
- It takes about 2 ms.

**The picture this builds**

```
START -> rules --after_rules--> classify --after_classify--> answer_known -> END
                    |                                  \--> answer_large -> END
                    \--(a rule matched)--> answer_known / answer_large
```

**Why it is a function and not top-level code:** the tests need to build a second graph with a checkpointer and a pause (`interrupt_before=["answer_large"]`). A function lets them do that without changing the normal graph.

---

## Step 12: lines 192–229 (the compiled graph and the entry point)

```python
ROUTER_GRAPH = build_router_graph()
```

**Line 192: compile once**
- This runs when the module is imported and takes about 2 ms.
- `ROUTER_GRAPH` is the normal graph, with no checkpointer and no pause. Every request uses this same object.
- It is safe to share because the graph holds no per-request data. The clients arrive through the context.

```python
def result_from_state(state: RouterState, total_latency_ms: float) -> RouterResult:
    return RouterResult(
        intent=state["intent"],
        rule_matched=state["rule_matched"],
        answer=state["answer"],
        answer_model=state["answer_model"],
        answer_backend=state["answer_backend"],
        classify_latency_ms=state.get("classify_latency_ms", 0.0),
        answer_latency_ms=state["answer_latency_ms"],
        total_latency_ms=total_latency_ms,
        classify_usage=state.get("classify_usage"),
        answer_usage=state.get("answer_usage"),
    )
```

**Lines 195–207: state to result**
- This converts the final state dict into the `RouterResult` that `route()` also returns, so the two flows are interchangeable for callers.
- Keys that every finished run has use `state["..."]`: `intent`, `rule_matched`, `answer`, the model and backend, and the answer latency.
- Keys that may be missing use `.get(...)`:
  - `classify_latency_ms` falls back to `0.0`.
  - `classify_usage` falls back to `None`.
- The total latency does not come from the state. The caller measures it and passes it in.

```python
async def route_with_graph(
    message: str,
    *,
    small_client: LLMClient,
    large_client: LLMClient,
    context: CallContext | None = None,
    max_tokens: int = 512,
    large_max_tokens: int = 2000,
) -> RouterResult:
    """Same signature and result as `router_service.route()`, run through the graph."""
```

**Lines 210–218: the public function**
- Its parameters are the same as `route()`. That is deliberate. The test can call either one with the same arguments, and the API could switch between them by changing one name.
- Only `message` is positional. Everything after `*` must be passed by name.

```python
    deps = RouterDeps(
        small_client,
        large_client,
        context or CallContext(feature="router"),
        max_tokens,
        large_max_tokens,
    )
```

**Lines 220–226: build the run's context**
- It packs the clients, the caller's context and the caps into one `RouterDeps` object.
- `context or CallContext(feature="router")` supplies a default context when the caller passes none.

```python
    started = time.perf_counter()
    state = await ROUTER_GRAPH.ainvoke({"message": message}, context=deps)
    return result_from_state(state, round((time.perf_counter() - started) * 1000, 1))
```

**Lines 227–229: run the graph**
- **Line 227:** start the stopwatch for the total latency.
- **Line 228:** `ainvoke` runs the whole graph.
  - The first argument is the starting state, which holds only the message.
  - `context=deps` is what the nodes read with `runtime.context`.
  - It returns the final state, with every key the nodes set.
- **Line 229:** measure the elapsed time in ms, convert the state to a `RouterResult` and return it.

**Where the time goes.** The total includes the graph's own work, which was about 2 ms in the comparison, plus the model calls. That is why the total latency can't be a sum of the classify and answer latencies alone.

---

## The whole file in one picture
1. `route_with_graph` packs the clients into `RouterDeps` and calls `ROUTER_GRAPH.ainvoke`.
2. The graph walks the nodes: `rules`, then maybe `classify`, then `answer_known` or `answer_large`.
3. Each node reads the state, may read the clients from the context, and returns a few keys.
4. Edge functions read the state and pick the next node.
5. `result_from_state` turns the final state into the `RouterResult`.

### One request through the graph
"How much is the course?" goes `START` → `rules` (no match) → `after_rules` says `classify` → `classify` (the model replies `fees`) → `after_classify` says `answer_known` → `answer_known` (the small model answers with `router_fees` v2) → `END`.

A greeting like "Hi" matches a rule, so `rules` sets the intent and `after_rules` skips `classify`. It goes straight to `answer_known`, which makes one model call.
