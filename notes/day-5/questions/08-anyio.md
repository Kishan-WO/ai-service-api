# Q30. What is anyio?

`anyio` is a Python library providing a **single async API on top of `asyncio` or `trio`**. Starlette (FastAPI's base) is built on it, so it's already installed.

## In your code
```python
with anyio.CancelScope(shield=True):
    await events.aclose()
    await persist()
```

## What `CancelScope` is
A block of code with its own cancellation rules. Normally when a task is cancelled (client disconnects), the next `await` raises `CancelledError`. `shield=True` makes the scope **immune to outside cancellation**, so awaits inside run to completion.

## Why needed in `finally`
1. Server cancels the `chat_stream` task.
2. `CancelledError` raised; `except` then `finally` run.
3. `finally` must `await events.aclose()` and `await persist()` (DB write).

After cancellation, further awaits can be cancelled again, interrupting the DB save and losing the partial answer. The shield guarantees cleanup finishes.

## Why anyio and not plain asyncio
`asyncio.shield()` works on a single awaitable and behaves awkwardly. `CancelScope(shield=True)` shields a whole **block**. No extra dependency (Starlette uses anyio).

## Other uses
```python
await anyio.sleep(1)
await anyio.to_thread.run_sync(blocking_fn)
async with anyio.create_task_group() as tg:
    tg.start_soon(task_a); tg.start_soon(task_b)
anyio.fail_after(5)
```
FastAPI's `run_in_threadpool` uses `anyio.to_thread` internally.
