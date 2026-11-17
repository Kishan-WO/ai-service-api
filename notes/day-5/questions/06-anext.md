# Q28. What is `anext()`?

A built-in (Python 3.10+) that **gets the next item from an async iterator**: the async version of `next()`; must be awaited.
```python
async def numbers():
    yield 1
    yield 2

gen = numbers()
await anext(gen)   # 1
await anext(gen)   # 2
await anext(gen)   # StopAsyncIteration
```

## Compared to `next()`
```python
next(iterator)             # sync
await anext(async_iter)    # async
```
Equivalent to `await async_iter.__anext__()`.

## Default value
```python
item = await anext(gen, None)   # None instead of StopAsyncIteration
```

## Relation to `async for`
`async for` calls `anext` repeatedly and stops on `StopAsyncIteration`. `anext()` pulls **one item manually**.

## Common uses
**Peek at the first chunk of a stream** to fail early:
```python
stream = provider.stream(prompt)
first = await anext(stream, None)
if first is None:
    raise EmptyResponseError()

async def body():
    yield first
    async for chunk in stream:
        yield chunk

return StreamingResponse(body())
```
**Drive a dependency generator in tests:**
```python
gen = get_db_session()
session = await anext(gen)
await anext(gen, None)   # commit + close
```

## Notes
- Only works on **async** iterators (`TypeError` otherwise).
- Before 3.10: `await gen.__anext__()`.
- After exhaustion keeps raising `StopAsyncIteration`.
- If you stop early, call `await gen.aclose()` so cleanup (`finally`) runs.
