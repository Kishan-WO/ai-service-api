# SQLAlchemy models: `Mapped`, `mapped_column` and timestamps

Question: explain `TimestampMixin` in `db/base.py` (I come from JavaScript).

```python
class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
```

## 1. A model is a class that maps to a table
| Mongoose | SQLAlchemy 2.0 |
|---|---|
| `new Schema({ name: String })` | `class Tenant(Base): name: Mapped[str] = mapped_column(String(255))` |
| Collection | Table (`__tablename__ = "tenants"`) |
| `timestamps: true` | A mixin such as `TimestampMixin` |
| One schema file | A class; `Base.metadata` collects all tables |

## 2. `Mapped[...]` and `mapped_column(...)`
- `Mapped[datetime]` is the **Python type** of the attribute. A type checker (mypy) uses it, and SQLAlchemy reads it to choose a default column type.
- `mapped_column(...)` describes the **database column**: its SQL type, constraints, defaults.
- `Mapped[str]` means not null; `Mapped[str | None]` means nullable.

| Argument | Meaning |
|---|---|
| `DateTime(timezone=True)` | SQL type `TIMESTAMP WITH TIME ZONE` |
| `nullable=False` | The column is `NOT NULL` |
| `default=...` | Value used when I create a row without giving one (set by Python) |
| `onupdate=...` | Value applied automatically whenever the row is updated |
| `primary_key=True`, `unique=True`, `index=True`, `ForeignKey(...)` | The usual constraints |

## 3. Why `lambda: datetime.now(UTC)`
```python
default=datetime.now(UTC)          # WRONG: evaluated once, when the class is defined
default=lambda: datetime.now(UTC)  # RIGHT: evaluated for every new row
```
The first writes the time the server **started** into every row. SQLAlchemy accepts a callable, so I pass a function that is called per row. This is the same trap as the mutable-default argument bug: a default is computed once unless it is a function.

## 4. Why time zones
`DateTime(timezone=True)` plus `datetime.now(UTC)` stores timestamps with the zone, in UTC. Without a zone, "10:30" means different moments in different places. Store UTC, convert for display.

## 5. `default` is set by Python, not by the database
- `default=` and `onupdate=` run **in my code** when SQLAlchemy builds the INSERT/UPDATE.
- A row inserted by raw SQL (or another program) would get no `created_at`, because the database column has no default.
- A database-side default would be `server_default=func.now()`. This project uses Python-side defaults.
- `onupdate` fires only for updates made **through SQLAlchemy** (changing the object and committing).

## 6. Why it is a mixin
`created_at` and `updated_at` are needed by `Tenant`, `User` and `Document`. One mixin class avoids three copies:

```python
class Document(Base, TimestampMixin): ...
```
How multiple inheritance and mixins work: `day-1/learning/mixins-and-multiple-inheritance.md`.

## 7. Related pieces in `base.py`
```python
class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=POSTGRES_INDEXES_NAMING_CONVENTION)
```
- `DeclarativeBase` is the parent of all models; it collects table definitions in `Base.metadata`.
- The **naming convention** gives every constraint and index a predictable name (`pk_users`, `fk_users_tenant_id_tenants`, `ix_users_email`). Alembic needs stable names to change or drop them later.

## Common mistakes
| Mistake | What happens |
|---|---|
| `default=datetime.now(UTC)` without `lambda` | Every row gets the start-up time |
| `DateTime()` without `timezone=True` | Naive timestamps; wrong times across zones |
| Expecting `onupdate` to run for raw SQL | It only runs for ORM updates |
| Mixing `Mapped[str]` with `nullable=True` | The checker and the database disagree |

## Quick check
- What is the difference between `Mapped[...]` and `mapped_column(...)`?
- Why is the default a `lambda`?
- What does `onupdate` do, and when does it not run?
- Why do `Tenant`, `User` and `Document` share one mixin?
