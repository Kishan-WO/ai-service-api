# Q1. What is base setting in FastAPI?

In FastAPI, **BaseSettings** is a Pydantic class used to manage app configuration (database URLs, secret keys, API keys, debug flags). It reads values from environment variables and `.env` files, validates them, and gives you a typed settings object.

## Setup
In Pydantic v2, `BaseSettings` lives in a separate package:
```bash
pip install pydantic-settings
```
(In Pydantic v1: `from pydantic import BaseSettings`.)

## Example
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "My API"
    debug: bool = False
    database_url: str
    secret_key: str

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
```
`.env`:
```
DATABASE_URL=postgresql://user:pass@localhost/db
SECRET_KEY=supersecret
DEBUG=true
```

## Using it in FastAPI
```python
from functools import lru_cache
from fastapi import FastAPI, Depends

@lru_cache
def get_settings():
    return Settings()

@app.get("/info")
def info(settings: Settings = Depends(get_settings)):
    return {"app_name": settings.app_name, "debug": settings.debug}
```

## Why use it
- **Type validation:** `DEBUG=true` becomes a real `bool`; a missing `DATABASE_URL` fails at startup.
- **Environment-based config:** same code in dev, staging, production.
- **Priority:** environment variables > `.env` values > class defaults.
- **Easy testing:** override with `app.dependency_overrides`.
