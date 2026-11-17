# Q23. Meaning of `cascade` in a relationship

```python
messages: Mapped[list[Message]] = relationship(
    "Message", back_populates="conversation",
    cascade="all, delete-orphan", order_by="Message.id",
)
```

`cascade` tells SQLAlchemy **what to do with related `Message` objects when something happens to their parent `Conversation`**. `"all, delete-orphan"` = apply every operation to children, and delete children that lose their parent.

## What `"all"` includes
- `save-update`: adding a conversation adds its messages.
- `merge`: merging also merges messages.
- `refresh-expire`: refresh/expire propagates.
- `expunge`: removing from the session removes messages.
- `delete`: deleting a conversation deletes its messages.

(`all` does not include `delete-orphan`.)

## `delete`
```python
await session.delete(conversation)
await session.commit()   # its Message rows are deleted too
```
Without it, SQLAlchemy would set `conversation_id` to `NULL`, failing if `NOT NULL`.

## `delete-orphan`
```python
conversation.messages.remove(msg)
await session.commit()   # msg's row is DELETED
```
Without it, only `conversation_id = NULL` would be set.

## Why used
A message has no meaning outside its conversation: the conversation **owns** its messages.

## Caveats
- **ORM-level only.** Bulk `delete(Conversation).where(...)` bypasses it; use DB-level `ondelete="CASCADE"`:
```python
conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
```
- **Async gotcha:** deleting needs messages loaded; lazy loading raises `MissingGreenlet`. Eager-load with `selectinload(...)`, or use `passive_deletes=True` + `ondelete="CASCADE"`:
```python
relationship("Message", back_populates="conversation",
             cascade="all, delete-orphan", passive_deletes=True, order_by="Message.id")
```
- `delete-orphan` requires a single parent.

## Other arguments
- `back_populates="conversation"`: keeps both sides in sync.
- `order_by="Message.id"`: creation order; a string avoids circular imports.
