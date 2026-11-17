# Q2. Why have brackets while assigning default "development"?

```python
ENVIRONMENT: Literal["development", "staging", "production", "testing"] = (
    "development"
)
```

The brackets are purely for **line formatting**. They don't change behavior. It's identical to the single-line version.

## Why they're there
The single-line version is longer than the default line limit of formatters like **Black** / **Ruff** (88). Python allows line breaks inside parentheses, so the formatter wraps the value in `( )`. Without brackets a line break would be a syntax error (unless you used `\`).

## Key points
- `("development")` is **not a tuple**. A tuple needs a comma: `("development",)`.
- Running `black` or `ruff format` adds these brackets automatically.
- To avoid them, define the type separately:
```python
EnvType = Literal["development", "staging", "production", "testing"]

class Settings(BaseSettings):
    ENVIRONMENT: EnvType = "development"
```
