# Q4. Explain this env_file syntax

```python
model_config = SettingsConfigDict(
    env_file=(BASE_DIR / ".env", ".env"),
```

`env_file` is given a **tuple of paths**. Pydantic Settings loads **every file in the tuple**, in order.

## The two entries
1. **`BASE_DIR / ".env"`**: absolute path to `.env` in the project root. `BASE_DIR` is usually `Path(__file__).resolve().parent.parent`. The `/` is `pathlib` path joining.
2. **`".env"`**: relative path, resolved against the **current working directory**.

## Why both
- The first works no matter where you start the app from.
- The second lets someone drop a `.env` in the cwd as a local override.

## Merging
- Later files **override earlier ones**.
- Missing files are **silently skipped**.
- Real **environment variables still beat both**.

Priority, highest to lowest:
1. Environment variables
2. `.env` in cwd
3. `.env` in `BASE_DIR`
4. Class defaults

If both paths are the same file, it's just loaded twice (harmless).

Variation: `env_file=(".env", ".env.production")` — the later file overrides.
