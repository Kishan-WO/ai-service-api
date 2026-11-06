# Transactions: why `commit` and `rollback` appear in some services only

Question: why does `auth_service.register` use `session.commit()` and `session.rollback()`, while the other service functions don't?

## 1. What a transaction is
A **transaction** groups database changes so they succeed or fail **together**.
- A SQLAlchemy session starts a transaction automatically on its first query.
- Changes (`session.add(...)`, updates, deletes) are held in that transaction.
- `commit()` makes them permanent. `rollback()` throws them away.
- If the session closes without a commit, the changes are lost.

## 2. Reads need no commit
`SELECT` queries change nothing, so there is nothing to save. These functions only read, and have no commit or rollback:

| Function | Kind |
|---|---|
| `authenticate` | read |
| `get_document` | read |
| `list_documents` | read |

## 3. Writes commit
| Function | Writes | Handling |
|---|---|---|
| `register` | a tenant and a user | `commit()`; `rollback()` if the insert hits `IntegrityError` |
| `create_document` | a document | `commit()`; `rollback()` on the duplicate race |
| `delete_document` | removes a document | `commit()` |

## 4. Why `register` and `create_document` also roll back
Both rely on a unique constraint (`users.email`, and `(tenant_id, content_hash)` for documents).

1. Request A and request B register the same email at the same moment.
2. Both pass the "does it exist" check.
3. A's `commit()` succeeds. B's `commit()` fails with `IntegrityError`.
4. After a failed commit the session is in a **broken state**: until it is rolled back, any further use raises an error.
5. So the code calls `rollback()`, then turns the database error into a friendly one (`EmailAlreadyRegisteredError`, a 409).

`delete_document` has no such race, so it needs no `try/except`.

## 5. Why not leave the commit to the session dependency
`get_db_session` also commits after `yield`, but FastAPI runs that code **after the response is sent**. I measured the order:

```
endpoint returns → response start → response body → dependency exit (commit)
```
A commit there can fail after the client has already been told "success", and the client might read the data before it is saved. So services commit **before they return**, and the dependency's commit is only a backstop.

## 6. A rule of thumb
| Situation | Do |
|---|---|
| Only reading | No commit |
| Writing | `await session.commit()` before returning the result |
| A write can violate a unique constraint | Wrap `commit()` in `try/except IntegrityError`, `rollback()`, raise a clear error |
| Several steps that must succeed together | Do them in one session and commit once at the end |

Express/Mongoose comparison: a unique index error (`E11000`) is caught in a `catch` block; the transaction idea is the same, but SQL makes "all or nothing" explicit.

## Common mistakes
| Mistake | What happens |
|---|---|
| No `commit()` after an insert | The row disappears when the session closes |
| Catching `IntegrityError` without `rollback()` | The next statement raises "transaction is inactive" |
| Committing in the middle of a multi-step operation | A later failure cannot undo the earlier part |
| Committing in a read function | Harmless but pointless |
| Relying on the dependency's commit | It runs after the response; failures are hidden from the client |

## Quick check
- What do `commit()` and `rollback()` do?
- Why do read-only functions not commit?
- Why does `register` roll back after `IntegrityError`?
- Why do the services commit themselves and not wait for the dependency?
