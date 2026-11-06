# Querying with `select()` and `session.scalar()`: the existence check

Question: explain line 28 in `auth_service.py`:

```python
if await session.scalar(select(User.id).where(User.email == email)):
    raise EmailAlreadyRegisteredError()
```

## 1. Building the query
`select(...)` builds an SQL statement as a Python object. Nothing runs yet.

```python
select(User.id).where(User.email == email)
# SELECT users.id FROM users WHERE users.email = :email
```
- `User.id` asks for **one column** only (not the whole row).
- `User.email == email` looks like a normal comparison but produces an SQL condition. The value goes in as a **bound parameter**, so it is safe from SQL injection.
- Compare with Mongoose: `User.findOne({ email })`, or `User.exists({ email })`.

## 2. Running it: the execute family
| Call | Returns |
|---|---|
| `await session.execute(stmt)` | A result object with rows (tuples) |
| `await session.scalars(stmt)` | A result of **single values** (first column), iterate or `.all()` |
| `await session.scalar(stmt)` | The **first column of the first row**, or `None` if there are no rows |
| `await session.get(User, user_id)` | Look up by **primary key** (checks the session's cache first) |

`session.scalar(...)` is the shortcut for "I need one value, or nothing".

## 3. How the check works
- Email found → `scalar` returns the user's `id` (a UUID, which is truthy) → `if` is true → raise "already registered".
- Email not found → `scalar` returns `None` → `if` is false → continue.

Why select only `User.id`: the database does not have to load the password hash and other columns, and no `User` object is built. It is a cheap "does it exist" test.

## 4. Why a check is not enough
Two requests with the same new email can both pass the check at the same moment, and then both try to insert. The database has the final say because the `email` column has a unique index, and the second insert raises `IntegrityError`. The service catches it:

```python
try:
    await session.commit()
except IntegrityError:
    await session.rollback()
    raise EmailAlreadyRegisteredError() from None
```
The check gives a fast, friendly answer in the normal case; the unique constraint guarantees correctness in the race case. See `transactions-commit-rollback.md`.

## 5. The tenant rule in queries
Every query on tenant data adds the tenant to the condition:
```python
select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
```
If the row belongs to another tenant, the result is `None`, exactly like a missing row, so the API answers 404 for both.

## Common mistakes
| Mistake | What happens |
|---|---|
| Treating `scalar()` as "all rows" | It returns only the first value |
| `if session.scalar(...)` without `await` | The coroutine object is always truthy; the check never fails |
| Selecting the whole `User` just to test existence | Wastes work and memory |
| Using `== None` | Use `.is_(None)` in SQLAlchemy conditions |
| Relying on the check alone | A race can still insert a duplicate; keep the unique constraint |

## Quick check
- What does `select(User.id).where(...)` build, and when does it run?
- What does `session.scalar()` return when nothing matches?
- Why select only the `id` for an existence test?
- Why is the database's unique constraint still needed after the check?
