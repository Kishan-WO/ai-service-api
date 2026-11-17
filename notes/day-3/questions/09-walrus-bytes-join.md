# Q22. Meaning of `:=` and `b"".join(...)`

```python
async def read_upload(file: UploadFile, max_bytes: int) -> bytes:
    if file.size is not None and file.size > max_bytes:
        raise PayloadTooLargeError(max_bytes)
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_CHUNK_SIZE):
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLargeError(max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)
```

## `:=` (walrus operator)
An **assignment expression**: assigns a value and returns it inside a larger expression.
```python
while chunk := await file.read(_CHUNK_SIZE):
```
Reads a chunk, assigns to `chunk`, uses it as the condition: non-empty bytes truthy, `b""` (EOF) falsy → loop stops.

Without it:
```python
while True:
    chunk = await file.read(_CHUNK_SIZE)
    if not chunk:
        break
```
Notes: `await` works inside; parentheses needed outside `if`/`while` (`x = (y := 5)`); `chunk` remains after the loop (`b""`).

## `b"".join(chunks)`
`b""` is an empty **bytes literal**; `.join()` concatenates bytes objects with nothing between.
```python
b"".join([b"hel", b"lo ", b"world"])   # b"hello world"
```
Bytes equivalent of `"".join(strings)`.

### Why not `+=`
Bytes are immutable; each `+=` copies everything so far (quadratic). `join` computes total size once and copies each chunk once.

## How the function works
- **Fast path:** reject immediately if `file.size` already exceeds the limit.
- **Safe path:** `file.size` can be `None`/untrustworthy, so count bytes as they're read and stop at the limit: a malicious client can't make you load 5 GB.
- Join chunks at the end.

Chunked reading checks the limit **during** reading, not after.
