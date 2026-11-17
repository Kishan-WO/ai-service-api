# Exception handlers: Express vs FastAPI

## The Express habit
In Express everything is an **ordered array** that runs top to bottom, so position decides behaviour:
```javascript
app.use(logger);
app.use("/api", router);
app.use(errorHandler);   // must come after the router, or it never sees the router's errors
```
Put `errorHandler` above the router and it runs first, before any error exists.

## What FastAPI (Starlette) does instead
Exception handlers are not a list. They are a **lookup table**: exception class → handler function.
```python
app.add_exception_handler(AppError, handle_app_error)
app.add_exception_handler(Exception, handle_unexpected_error)
# stored in app.exception_handlers, a dict
```
So **the order of `register_error_handlers(app)` and `app.include_router(...)` in `main.py` does not matter** for exception handlers. Both are loaded before the first request. The convention is still: settings, create the app, middlewares and error handlers, then routers.

The stack of middleware is built once, on the first request (`build_middleware_stack`).

## How the lookup really works
Two details matter, and one common explanation gets them wrong.

1. **The match walks the exception's class hierarchy**, not just its exact type. Starlette does:
   ```python
   for cls in type(exc).__mro__:      # DocumentNotFoundError, AppError, Exception, BaseException, object
       if cls in handlers:
           return handlers[cls]
   ```
   A plain `handlers.get(type(exc))` would never find a handler for `DocumentNotFoundError`, because only `AppError` is registered. The hierarchy walk is what makes one `AppError` handler serve every subclass (`NotAuthenticatedError`, `DuplicateDocumentError`, ...). The first class in the walk that has a handler wins, so a more specific handler beats a general one.
2. **The handlers do not all run in the same place.** In `build_middleware_stack`:
   ```python
   for key, value in self.exception_handlers.items():
       if key in (500, Exception):
           error_handler = value          # goes to ServerErrorMiddleware (outermost)
       else:
           exception_handlers[key] = value  # goes to ExceptionMiddleware (inner)
   ```
   - Handlers for `AppError`, `HTTPException`, `RequestValidationError` live in `ExceptionMiddleware`, **inside** the user middlewares.
   - The `Exception` (and 500) handler lives in `ServerErrorMiddleware`, **outside** them.

## What does depend on order: middleware
Middleware is a real ordered stack, as in Express:
```python
app.add_middleware(CORSMiddleware, ...)
app.add_middleware(RequestContextMiddleware)   # added last, so it is outermost
```
`add_middleware` inserts at the front, so **the last one added runs first** on the way in and last on the way out. Adding middleware after the app has started raises `RuntimeError: Cannot add middleware after an application has started`.

| | Express | FastAPI / Starlette |
|---|---|---|
| Routes and middleware | ordered array | middleware: ordered stack (last added = outermost); routes: matched by path |
| Error handlers | one function at the end of the array | a dict of class → handler, order irrelevant |
| Which error handler runs | the last one in the array | the most specific class in the exception's hierarchy |
| Errors thrown inside middleware | reach the error handler | only reach `ServerErrorMiddleware` if the middleware sits outside `ExceptionMiddleware` |

That last row is the practical consequence: an exception raised by `RequestContextMiddleware` itself would **not** go through `handle_app_error` or the 422 handler, because those run below it. Only the generic 500 handler would see it.

## Corrections to a common explanation
A short summary of this topic often says things that are close but not exact. Checked against Starlette 1.10:

| Claim | Reality |
|---|---|
| "It is a dictionary lookup, so registration order does not matter" | True for exception handlers |
| "FastAPI looks up `app.exception_handlers.get(type(exc))`" | Not exactly: it walks `type(exc).__mro__`, so subclasses reuse a parent's handler |
| "If any route, dependency **or middleware** throws, FastAPI catches it with one try/except" | Route and dependency errors are caught by `ExceptionMiddleware`. Errors from user middleware are outside it, so only the 500 handler catches them |
| "Order does not matter in FastAPI" (in general) | Only for exception handlers. Middleware order does matter |

## What I applied in ai-service
- One handler for the base class `AppError`, and every error class is a subclass with its own `status_code` and `code`. Adding a new error means adding a class, not a handler.
- Separate handlers for Starlette's `HTTPException` (404/405 for unknown routes) and `RequestValidationError` (422), so framework errors use the same envelope.
- A handler for `Exception` for bugs: generic message to the client, traceback in the log. Because it runs outside my middleware, it adds `X-Request-ID` itself.

## Quick check
- Why does one `AppError` handler also handle `DocumentNotFoundError`?
- Which two middlewares/layers do the 500 handler and the 404 handler live in?
- What happens if I call `add_middleware` after the first request?
- Does moving `register_error_handlers(app)` below `include_router` change behaviour? What about moving `add_middleware` calls around?
