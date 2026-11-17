# Q25. Explain `scalars` and `*scope`

```python
async def list_conversations(session: AsyncSession, *, tenant_id, user_id, limit: int, offset: int):
    scope = (Conversation.tenant_id == tenant_id, Conversation.user_id == user_id)
    total = await session.scalar(select(func.count()).select_from(Conversation).where(*scope))
    rows = await session.scalars(
        select(Conversation).where(*scope)
        .order_by(Conversation.updated_at.desc(), Conversation.id)
        .limit(limit).offset(offset)
    )
    return list(rows), total or 0
```

## `scope` and `*scope`
`scope` is a **tuple of two filter conditions**. `Conversation.tenant_id == tenant_id` isn't `True/False`: SQLAlchemy overloads `==` to build a SQL expression.

`.where(*scope)` **unpacks the tuple into separate arguments**, same as `.where(cond1, cond2)`, combined with `AND`:
```sql
WHERE conversations.tenant_id = :t AND conversations.user_id = :u
```
### Why define once
Count and list queries must filter **identically**; also a clean place to enforce multi-tenant isolation. (This `scope` has nothing to do with the ASGI `scope`.)

## `scalar` vs `scalars`
- **`session.scalar(...)`**: first column of the first row: a single value or `None`. Good for counts. Hence `total or 0`.
- **`session.scalars(...)`**: first column of **every row** as an iterable `ScalarResult`. For `select(Conversation)` you get the objects directly, whereas `execute()` gives `(Conversation,)` tuples.

## Count query
`func.count()` → `COUNT(*)`; `.select_from(Conversation)` tells SQLAlchemy the table.
```sql
SELECT count(*) FROM conversations WHERE tenant_id = :t AND user_id = :u
```

## List query
- Newest-updated first, `id` as **tiebreaker** (stable pagination without duplicates/skips).
- `limit` = page size, `offset` = rows to skip.

## `*` in the signature
Keyword-only parameters, so UUIDs can't be mixed up by position.

## Return
`(conversations on this page, total matching count)`.
