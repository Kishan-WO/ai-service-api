# Day 5: `/chat` (streaming, stored) and `/extract` (structured output)

What was added to `ai-service` on Day 5, how it fits together, and how to run it.

## 1. New endpoints
| Endpoint | What it does |
|---|---|
| `POST /api/v1/chat` | Send a message (and optionally a `conversation_id`), get the answer streamed as Server-Sent Events; both messages are stored |
| `GET /api/v1/chat/conversations` | My conversations, newest first (`limit`, `offset`) |
| `GET /api/v1/chat/conversations/{id}` | One conversation with all its messages |
| `DELETE /api/v1/chat/conversations/{id}` | Delete it (and its messages) |
| `POST /api/v1/extract` | Messy text in, a validated `Enquiry` object out |

Both `/chat` and `/extract` take `"backend": "hosted"` (Gemini, default) or `"local"` (Ollama).

## 2. Files
```
db/models/conversation.py      Conversation, Message (tenant_id on both)
alembic/versions/c2b3d69c8756  the migration (tested up, down, up on PostgreSQL)
services/llm.py                LLMProvider protocol, OpenAI-compatible provider, registry
services/chat_service.py       queries + chat_stream(), the SSE generator
services/extract_service.py    schema -> model -> validate -> one retry
schemas/chat.py, extract.py    request/response models, and the Enquiry shape
api/v1/chat.py, extract.py     the routes
api/deps.py                    + get_llm_registry, get_session_factory
scripts/compare_extract.py     task 5: hosted vs local on 10 messages
tests/fakes.py                 FakeProvider / FakeRegistry (no network in tests)
```

## 3. The `/chat` flow
```
POST /chat {message, conversation_id?, backend?}
 1. authenticate; load the conversation (404 if not mine) and its last 20 messages
 2. open the upstream stream and WAIT for the first event
       provider down  -> 502, nothing stored
       client already gone -> close upstream, nothing stored (499)
 3. store the conversation (if new) + the user message, commit
 4. return StreamingResponse:
       event: start   {conversation_id, user_message_id, model}
       event: token   {text}                     (many)
       event: done    {message_id, stop_reason, input_tokens, output_tokens}
       event: error   {code, message}            (instead of done, if the provider fails mid-way)
 5. when the stream ends - for any reason - close the upstream call and save the assistant message
       complete   the model finished
       cancelled  the client left: the partial text is kept
       error      the provider failed: the partial text is kept
```
The message array sent to the model is `[system prompt] + last N stored messages + the new message` (see the diagram in `ai-eng-learning/day-5/learning/1.messages-api.md`).

## 4. Tables
`conversations`: `id (uuid)`, `tenant_id`, `user_id`, `title`, `created_at`, `updated_at`.
`messages`: `id (bigint, increasing)`, `conversation_id`, `tenant_id`, `role`, `content`, `status`, `model`, `stop_reason`, `input_tokens`, `output_tokens`, `created_at`, `updated_at`.
Every query filters by tenant and user; someone else's conversation is a `404`.

## 5. Running it
```bash
# .env: DATABASE_URL, SECRET_KEY, and for the hosted model LLM_API_KEY + LLM_MODEL (see .env.example)
uv run alembic upgrade head
uv run uvicorn ai_service.main:app --reload
```
Local PostgreSQL used for the Day 5 work: database `day5-chat-extract` on `localhost:5432`.
```bash
curl -N -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer <token>" -H "content-type: application/json" \
  -d '{"message": "Hello", "backend": "local"}'
```
Tests: `uv run pytest` (73 tests, no network, no key, no Docker).

## 6. Evidence from real runs
See `ai-eng-learning/day-5/Notes/` for the measured results (stream, disconnect, hosted vs local extraction).
