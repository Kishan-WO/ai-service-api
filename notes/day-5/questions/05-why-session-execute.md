# Q27. Why `session.execute` (not explained before)?

```python
await session.execute(
    update(Conversation)
    .where(Conversation.id == conversation_id)
    .values(updated_at=datetime.now(UTC))
)
```

`session.execute(...)` runs a **SQL statement directly**, bypassing ORM object tracking:
```sql
UPDATE conversations SET updated_at = :now WHERE id = :conversation_id
```

## Why not like `start_turn`?
In `start_turn` the object is in memory, so `conversation.updated_at = ...` is tracked. In `save_assistant_message`:
- It's a **brand-new session**; the `Conversation` isn't loaded.
- The object from `start_turn` belongs to a closed session.
- The function only receives `conversation_id`.

ORM style would need:
```python
conversation = await session.get(Conversation, conversation_id)   # extra SELECT
conversation.updated_at = datetime.now(UTC)                       # then UPDATE
```
Two round trips, loading a whole row. `execute(update(...))` is **one round trip**, one column.

## Why `execute` and not `add`
`add()` is for ORM **objects**; `update(...)` is a **statement**.

| Goal | Method |
|---|---|
| Insert new object | `session.add(obj)` |
| Change a loaded object | set attribute |
| Change rows by condition, nothing loaded | `await session.execute(update(...))` |
| Read rows | `execute(select(...))` / `scalars(...)` |

## Order of operations
With `autoflush=False`, the pending message INSERT isn't flushed before the UPDATE; both go out before `commit()` in the **same transaction**. Order doesn't matter since they're independent.

## Benefit
Atomic in the database; no read-modify-write race.

## Caveat
Bulk `update()` bypasses ORM events and doesn't update already-loaded objects. Fine here: no `Conversation` is loaded and the session closes right after.
