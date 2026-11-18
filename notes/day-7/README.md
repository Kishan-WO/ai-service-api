# Day 7: prompt engineering (task implementation)

**Build target (from the plan):** a prompt registry plus a measured before/after prompt improvement. The concept notes are in `ai-eng-learning/day-7/learning/`.

**How this day is done:** I type the code myself, one small step at a time. This folder keeps the log of the steps and the questions I asked.

## The tasks (from the plan)
| Task | What | Status |
|---|---|---|
| 1 | Prompt registry: `prompts/<name>/vN.md`, loaded by name and version; the version stored in the request logs | done |
| 2 | Move every prompt in `ai-service` into the registry | done: `/extract` and `/chat` prompts are all registry files |
| 3 | Choose one prompt to improve (the classifier) | decided |
| 4 | A 30-case labelled test set | done (hard set + independent easy set) |
| 5 | Measure v1 zero-shot, v2 structure, v3 few-shot, v4 chain-of-thought | done, two runs |
| 6 | Keep the cheapest version within 2 points of the best; record it in `decisions.md` | v2 (`decisions.md` 42) |
| Notes | A personal prompt-writing checklist (`ai-eng-learning/day-7/Notes/`) | done |

## Steps done so far (task 1)
| Step | What | Files |
|---|---|---|
| 1 | Branch `day-7`; the first prompt, the zero-shot baseline `classify_query` v1 | `src/ai_service/prompts/classify_query/v1.md` |
| 2 | `jinja2` added; the first loader: `Prompt`, `get_prompt(name, version)`, `StrictUndefined` | `src/ai_service/services/prompt_registry.py`, `pyproject.toml`, `uv.lock` |

Steps 3 to 12 (name validation and cache, prompt name and version on `CallContext`, the log line, the `llm_calls` columns and migration, and `/extract` reading its three prompts from the registry) are described in `ai-eng-learning/day-7/Notes/tasks-1-6-prompt-registry-and-measured-prompts.md`.

## In this folder
- [questions/](questions/README.md): every question I asked while doing Day 7.
