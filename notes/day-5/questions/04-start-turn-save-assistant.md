# Q26. Explain the session logic in `start_turn` and `save_assistant_message`

```python
async def start_turn(session, *, tenant_id, user_id, conversation, user_text):
    if conversation is None:
        conversation = Conversation(tenant_id=tenant_id, user_id=user_id,
            title=user_text[:117] + "..." if len(user_text) > 120 else user_text)
        session.add(conversation)
        await session.flush()
    message = Message(conversation_id=conversation.id, tenant_id=tenant_id,
                      role="user", content=user_text, status=STATUS_COMPLETE)
    session.add(message)
    conversation.updated_at = datetime.now(UTC)
    await session.commit()
    return conversation, message


async def save_assistant_message(session_factory, *, tenant_id, conversation_id,
                                 content, status, model, finish) -> int:
    async with session_factory() as session:
        message = Message(conversation_id=conversation_id, tenant_id=tenant_id,
            role="assistant", content=content, status=status, model=model,
            stop_reason=finish.stop_reason if finish else None,
            input_tokens=finish.input_tokens if finish else None,
            output_tokens=finish.output_tokens if finish else None)
        session.add(message)
        await session.execute(update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=datetime.now(UTC)))
        await session.commit()
        return message.id
```

## Overview
Two transactions:
1. `start_turn`: inside the request, using the **request's session**; saves the user message (and new conversation).
2. `save_assistant_message`: after the LLM finishes, using a **brand-new session**.

## `start_turn`
1. **Create conversation if needed**: `add()` stages it in memory (`autoflush=False`); `await flush()` sends the `INSERT` **without committing** so `conversation.id` is available. Title is truncated to 117 chars + `...` when > 120.
2. **Add user message**: uses `conversation.id`; `add(message)` stages it; `conversation.updated_at = ...` is dirty-tracked and emitted as `UPDATE` at commit (bumps it in `list_conversations`).
3. **Commit once**: message INSERT + UPDATE + earlier flushed conversation INSERT all in one transaction: all or nothing. With `expire_on_commit=False`, returned objects are still readable.

## `save_assistant_message`
- **Separate session**: the request's session is "long gone" when streaming finishes, so it takes the **factory** and opens a fresh session (`async with` closes it).
- `finish` can be `None` (cancelled/failed), hence `finish.x if finish else None`; `status` stores e.g. complete/cancelled/error.
- **Direct `update()`** avoids loading the `Conversation` (no extra SELECT).
- Commit both atomically; `message.id` readable thanks to `expire_on_commit=False`.
- No explicit rollback: if something raises, the session closes uncommitted and work is discarded.

## Comparison
| | `start_turn` | `save_assistant_message` |
|---|---|---|
| Session | passed in (request's) | created from a factory |
| Timestamp update | modify loaded object | direct `update()` |
| `flush()` | yes, for new conversation id | not needed |
| Commits | itself | itself |

## Things to know
- They commit themselves, bypassing `get_db_session`'s commit: the user's message must be saved **before** the LLM call.
- Two transactions: a crash mid-stream leaves the user message without a reply, hence `status`.
- `message.id` is an `int`, `conversation_id` a UUID.
