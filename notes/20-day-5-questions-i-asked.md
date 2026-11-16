# Day 5: questions I asked while reading the code, and the answers

## 4. What is `__table_args__ = (Index("ix_messages_conversation_id_id", "conversation_id", "id"),)`?
- It is a composite index on `messages`, declared in the model. `__table_args__` is where SQLAlchemy takes table-level settings.
- The trailing comma makes it a one-item tuple. Without it SQLAlchemy complains.
- The main query is "last N messages of this conversation, oldest first": `WHERE conversation_id = ... ORDER BY id`. The index is already grouped by conversation and sorted by `id`, so Postgres does not scan the table or sort afterwards.
- The order matters: the filter column first, the sort column second.
- I sort by `id` and not by `created_at` because the id always increases, even when two messages are saved in the same millisecond.

## 5. What is the difference between `pass` and `...`?
- Both make an empty body that does nothing. `pass` is a statement. `...` is the `Ellipsis` object, an expression.
- `pass` says "empty on purpose": empty `except`, empty class.
- `...` says "only the shape" or "not written yet": `Protocol` methods, abstract methods, stubs. I use it only in the `LLMProvider` protocol.
- `...` also means "any number" in `tuple[int, ...]`, and "all the other dimensions" in numpy.