# Day 5: LLM integration I (`/chat` and `/extract`)

**Build target (from the plan):** `POST /chat` (streaming) and a first `POST /extract` in `ai-service`. The five tasks are one feature, so they were built together. The concept notes (messages API, streaming, structured output) and the real results are in `ai-eng-learning/day-5/`.

## Tasks, in the order of the plan

| Task | What it asked | Where it was built |
|---|---|---|
| **1** | Tables `conversations` and `messages`, scoped by tenant | `db/models/conversation.py`, migration `c2b3d69c8756` |
| **2** | `POST /chat`: history, SSE streaming, save the assistant message | `api/v1/chat.py`, `services/chat_service.py`, `services/llm.py` |
| **3** | Stop the upstream stream when the client disconnects; verify in the logs | `chat_stream()` |
| **4** | `POST /extract`: native structured output into a Pydantic model | `api/v1/extract.py`, `services/extract_service.py`, `schemas/extract.py` |
| **5** | The same `/extract` with the local Ollama model; compare | `scripts/compare_extract.py` |

## Notes in this folder
| # | Note |
|---|---|
| 01 | [`/chat` (streaming, stored) and `/extract` (structured output): files, the flow, how to run](01-chat-and-extract.md) |
| questions | [Questions and answers](questions/README.md), in implementation order: data model, the LLM interface, saving messages, streaming, disconnects |

Real outputs, the disconnect evidence and the hosted vs local comparison: `ai-eng-learning/day-5/Notes/tasks-1-5-chat-and-extract.md`.

Previous: [Day 3](../day-3/README.md). Next: [Day 6](../day-6/README.md).
