# Q15. Meaning of `*` in a parameter list (AppError)

```python
class AppError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"
    message = "Something went wrong."

    def __init__(self, message: str | None = None, *, details: Any = None,
                 headers: dict[str, str] | None = None) -> None:
        self.message = message or self.message
        self.details = details
        self.headers = headers
        super().__init__(self.message)
```

The bare `*` means **everything after it must be passed as a keyword argument**. It's just a separator.

```python
AppError("Not found")                              # ok
AppError("Not found", details={"id": 5})           # ok
AppError(message="Not found", details={"id": 5})   # ok
AppError("Not found", {"id": 5})                   # TypeError
```

## Why
- **Readability:** `AppError("Bad input", details=errors)`.
- **Safety:** can't swap `details` and `headers` by position.
- **Easy to extend:** add/reorder keyword-only params without breaking callers.

## Other special symbols
```python
def f(a, b, /, c, d, *, e, f): ...
```
Before `/`: positional-only; between: either; after `*`: keyword-only.

## Not `*args`
`*args` collects extra positional args into a tuple; a bare `*` collects nothing.

## Rest of the class
`self.message = message or self.message` falls back to the **class attribute**. Subclasses override class attributes:
```python
class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"
    message = "Resource not found."
```
