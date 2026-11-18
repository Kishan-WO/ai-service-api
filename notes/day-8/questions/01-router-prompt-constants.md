# Q44. What is the purpose of the three prompt name and version constants in `router_service.py`?

**What I asked:** "explain me purpose of this 3"

**Where it is:** `src/ai_service/services/router_service.py`
```python
_PROMPT_NAME: dict[str, str] = {intent: f"router_{intent}" for intent in KNOWN_INTENTS}
_PROMPT_VERSION = "v2"

_CLASSIFIER_PROMPT_NAME = "classify_query"
_CLASSIFIER_PROMPT_VERSION = "v5"

_GENERAL_PROMPT_NAME = "chat_system"
_GENERAL_PROMPT_VERSION = "v1"
```

## The short answer
They say which registry prompt file each step of the router loads, so the prompt text stays out of the code. A prompt file lives at `prompts/<name>/<version>.md` and is loaded with `get_prompt(name, version)`. The name and version are logged on every model call.

| Constants | Used by | What it loads |
|---|---|---|
| `_PROMPT_NAME` + `_PROMPT_VERSION` | the answer for a known intent | `router_admission`, `router_fees`, `router_schedule`, `router_academic`, `router_complaint`, `router_other`, version `v2` |
| `_CLASSIFIER_PROMPT_NAME` + `_CLASSIFIER_PROMPT_VERSION` | the classification step | `classify_query` `v5` |
| `_GENERAL_PROMPT_NAME` + `_GENERAL_PROMPT_VERSION` | the answer when the intent is `unclear` | `chat_system` `v1` (the full handbook) |

## One by one
1. **Specialised answer prompts.** The dict builds one name per known intent. With version `v2` the router loads `router_fees/v2.md` for a fees question. Each file holds only that intent's slice of the handbook (3.7K to 13K characters instead of 20.4K), so the small model reads less and the call costs less. `v1` was a generic placeholder, `v2` is the real-handbook version.
2. **Classifier prompt.** The small model reads the message and replies with one label. `v5` is the Day 7 `v2` prompt plus an `unclear` label. Without that label the classifier could never escalate, and the large-model path would never run.
3. **General prompt.** An `unclear` request has no specialised slice, so the large model answers with the full handbook. It is the same prompt `/chat` uses, and it is also the always-large baseline in the task 3 measurement.

## Why constants and not text inside the code
- To change a prompt I add a new version file and change one constant. The old version stays available for comparison.
- Every call's log row records the prompt name and version, so I can tell which version produced an answer.
