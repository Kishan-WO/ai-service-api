# Settings from `.env` with `pydantic-settings`

Question: why are there default values in `config.py`, what is `model_config`, and how do wrong values give an error?

## 1. What it does
`BaseSettings` is a Pydantic model that **fills its fields from environment variables** (and a `.env` file), then **validates** them like any other Pydantic model.

```python
class Settings(BaseSettings):
    DEBUG: bool = True
    SECRET_KEY: str = Field(..., min_length=32)
    DATABASE_URL: str = Field(...)
```
JavaScript comparison: `process.env` + `dotenv` + a validation library such as zod or joi, in one class. In Node, `process.env.PORT` is always a string and nothing checks it. Here `"1440"` becomes an `int` and a bad value stops the app.

## 2. Required fields and fields with a default
| Written as | Meaning |
|---|---|
| `SECRET_KEY: str = Field(..., min_length=32)` | **Required.** `...` means "no default". Missing or too short → error |
| `DEBUG: bool = True` | **Optional.** Uses `True` if nothing is set |
| `ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=1440, gt=0)` | Optional, but any value given must be greater than 0 |

### Why some fields have defaults and some do not
- **Safe, harmless settings** (`API_V1_PREFIX`, `ALGORITHM`, `MAX_UPLOAD_SIZE_BYTES`) get a default so a new developer can start the app with a short `.env`.
- **Secrets and connection strings** (`SECRET_KEY`, `DATABASE_URL`) have **no default**. A default secret key in code would be public and would silently run in production. The app must refuse to start instead.
- The rule: a default is fine when a wrong guess is harmless; never default a secret.

## 3. Wrong values fail at start-up
Real output with bad values set in the environment:
```
4 validation errors for Settings
ENVIRONMENT
  Input should be 'development', 'staging', 'production' or 'testing' [type=literal_error, input_value='prod']
SECRET_KEY
  String should have at least 32 characters [type=string_too_short, input_value='short']
DATABASE_URL
  Value error, DATABASE_URL must start with one of ('postgresql+asyncpg://', 'sqlite+aiosqlite://'). Got: mysql://x
ACCESS_TOKEN_EXPIRE_MINUTES
  Input should be greater than 0 [type=greater_than, input_value='0']
```
- All problems are reported **together**, not one by one.
- The tools used: `Literal[...]` for a fixed set of choices, `Field(min_length=..., gt=...)` for limits, and a `@field_validator` for the URL prefix.
- Failing at start is better than failing later in the middle of a request.

## 4. `model_config`
```python
model_config = SettingsConfigDict(
    env_file=(BASE_DIR / ".env", ".env"),
    env_file_encoding="utf-8",
    extra="ignore",
)
```
| Setting | Meaning |
|---|---|
| `env_file=(BASE_DIR / ".env", ".env")` | Read these `.env` files. `BASE_DIR` is the project folder, so it works whatever folder I start from. With several files, **later ones win** |
| `env_file_encoding="utf-8"` | Read the file as UTF-8 |
| `extra="ignore"` | A key in `.env` that is not a field is **ignored**. `"forbid"` would raise an error instead |

(`model_config` is the Pydantic v2 way to configure a model; v1 used an inner `class Config`.)

## 5. Where a value can come from (highest priority first)
1. Arguments passed to `Settings(...)`
2. **Real environment variables**
3. The `.env` file
4. The default in the class

Proof: with `PROJECT_NAME=from-env-var` set in the terminal, `Settings().PROJECT_NAME` was `from-env-var`, although `.env` says `ai-service`. This is why Docker Compose can override `DATABASE_URL` for the container.

Field names match environment variables **case-insensitively** by default.

## 6. Build it once: `get_settings()`
```python
@lru_cache
def get_settings() -> Settings:
    return Settings()
```
Reading and validating `.env` is done once; every caller gets the same object (see `day-1/learning/lru-cache-and-singleton.md`). FastAPI can also inject it with `Depends(get_settings)`, which tests can override.

## Common mistakes
| Mistake | What happens |
|---|---|
| A default value for `SECRET_KEY` | A weak key can reach production without anyone noticing |
| Editing `.env` while the app runs | Old values stay (cached) until restart |
| `.env` committed to git | Secrets leak; commit only `.env.example` |
| `extra="forbid"` with unrelated keys in `.env` | The app refuses to start |
| Expecting `.env` to beat a real environment variable | The real variable wins |

## Quick check
- What does `Field(...)` mean, and why do `SECRET_KEY` and `DATABASE_URL` use it?
- What happens at start-up when `SECRET_KEY` is too short?
- Which wins, an environment variable or the `.env` file?
- What does `extra="ignore"` do?
- Why is `get_settings()` wrapped in `@lru_cache`?
