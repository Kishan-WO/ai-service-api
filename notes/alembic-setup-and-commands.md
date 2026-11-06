# Alembic: setup, `env.py` and the commands

Question: the Alembic commands to run by hand, how to configure it, what `# noqa: F401` is for, and whether `env.py` is correct.

## 1. What Alembic is for
The database tables are described twice: as Python models, and as real tables in PostgreSQL. **Alembic keeps them in step** using versioned **migration** files, each one a small script with `upgrade()` and `downgrade()`.

Mongoose comparison: MongoDB has no fixed schema, so there is no equivalent. Closest are migration tools such as `migrate-mongo` or Prisma Migrate.

## 2. The files
| File | Role |
|---|---|
| `alembic.ini` | Settings: where the scripts live, logging |
| `alembic/env.py` | Python code Alembic runs for every command: connects to the database, finds my models |
| `alembic/versions/` | The migration files, one per change |
| `alembic/script.py.mako` | Template for new migration files |

Inside the database, one table `alembic_version` stores the id of the current migration.

## 3. What my `env.py` does
```python
import ai_service.db.models  # noqa: F401
target_metadata = Base.metadata
```
- Importing the models registers their tables in `Base.metadata`. `# noqa: F401` stops the linter deleting this "unused" import (see `day-2/Notes/noqa-and-linters.md`).
- `target_metadata` is what autogenerate compares with the real database.

```python
config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)
```
- `alembic.ini` has only a placeholder URL. `env.py` replaces it with the real one from my validated settings, so there is **one source of truth** (`.env`).

```python
connectable = async_engine_from_config(..., poolclass=pool.NullPool)
async with connectable.connect() as connection:
    await connection.run_sync(do_run_migrations)
```
- My app uses an async driver, so Alembic does too. `run_sync` runs Alembic's normal synchronous code on that async connection.
- `NullPool`: no pooling; the connection is closed after the migration.

```python
context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
```
- `compare_type=True` makes autogenerate notice changes of a column's **type** (for example `String(100)` → `String(255)`); by default only added or removed columns are detected.

`run_migrations_offline()` is used with `--sql`: it prints SQL instead of running it.

## 4. The commands
| Command | What it does |
|---|---|
| `uv run alembic revision --autogenerate -m "create tables"` | Compare models with the database and **write** a migration file |
| `uv run alembic upgrade head` | Apply all migrations not yet applied |
| `uv run alembic downgrade -1` | Undo the last migration |
| `uv run alembic downgrade base` | Undo everything (drops tables and data!) |
| `uv run alembic current` | Which migration the database is on |
| `uv run alembic history --indicate-current` | All migrations, with the current one marked |
| `uv run alembic heads` | The newest migration(s) |
| `uv run alembic check` | Do the models and the database match? Prints "No new upgrade operations detected." when yes |
| `uv run alembic upgrade head --sql` | Print the SQL without running it |

Words: `base` = before the first migration, `head` = the newest one, `-1` = one step back.

## 5. The everyday workflow
1. Change a model (add a column).
2. `alembic revision --autogenerate -m "add column"`.
3. **Open the new file and read it.** Autogenerate misses some things (renames look like a drop plus an add) and can include unwanted changes.
4. `alembic upgrade head`.
5. Check with `alembic check` or by looking at the table.

Real output when I applied the first migration:
```
INFO  [alembic.runtime.migration] Running upgrade  -> a7920f359d11, empty message
```
("empty message" only because I ran `revision` without `-m`.)

## 6. Alembic in Docker
The `api` service starts with `alembic upgrade head && uvicorn ...`, so a fresh `docker compose up` creates the tables before the app serves requests. If a migration fails, uvicorn does not start.

## 7. `history` vs `current`: why the output did not change after a downgrade
I ran `alembic history` before and after `alembic downgrade base` and saw the same line both times:
```
<base> -> a7920f359d11 (head), empty message
```
- `alembic history` lists the **migration files** in `alembic/versions/`. A downgrade changes the database, not the files, so the list is the same.
- `alembic current` reads the table `alembic_version` in the **database**. After `downgrade base` it prints nothing; after `upgrade head` it prints `a7920f359d11 (head)`.
- `alembic history --indicate-current` shows the files and marks which one the database is on.

| Command | Looks at |
|---|---|
| `history` | the files |
| `current` | the database |
| `check` | models vs database |

After `downgrade base` the database had only `alembic_version`, with 0 rows. `upgrade head` brought the three tables back.

## Common mistakes
| Mistake | What happens |
|---|---|
| Forgetting to import the models in `env.py` | Autogenerate sees no tables and writes an empty migration |
| Not reading the generated file | Wrong or dangerous changes get applied |
| Editing an applied migration | The database and the file disagree; make a new migration instead |
| `downgrade base` on a database with real data | The data is deleted |
| Running `revision` without `-m` | A migration named "empty message" |
| Pointing Alembic at the wrong database | Check `DATABASE_URL` (host port 5433 for the Docker Postgres) |

## Quick check
- What problem do migrations solve?
- Why does `env.py` import the models and use `# noqa: F401`?
- What does `compare_type=True` add?
- What is the difference between `upgrade head` and `downgrade base`?
- Why must I read an autogenerated migration before applying it?
