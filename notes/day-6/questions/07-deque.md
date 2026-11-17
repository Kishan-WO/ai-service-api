# Q35. Why use `deque`?

A `deque` (double-ended queue, `collections`) is used because the code **removes from the left end repeatedly**: O(1) for a `deque`, O(n) for a `list`.

## Access pattern
```python
self._starts.append(now)      # add newest on the right
self._starts[0]               # peek oldest on the left
self._starts.popleft()        # remove oldest from the left
```
A **FIFO queue**: oldest timestamps expire first.

## Why not a list
`list.pop(0)` shifts every remaining element: O(n). `deque.popleft()` is O(1). With `per_minute=60` the difference is tiny, but a deque states intent and scales if the limit is large.

| Operation | `list` | `deque` |
|---|---|---|
| `append` (right) | O(1) | O(1) |
| `pop()` (right) | O(1) | O(1) |
| `pop(0)` / `popleft()` | **O(n)** | **O(1)** |
| `appendleft` / `insert(0, x)` | **O(n)** | **O(1)** |
| `x[0]`, `x[-1]` | O(1) | O(1) |
| `x[i]` (middle) | O(1) | O(n) |

The weakness (middle access) isn't used here.

## Naming
It's `deque` ("deck"), not "dequeue" (the verb).

## `maxlen`
`deque(maxlen=60)` auto-drops from the opposite end when full. Not used here because dropping must be by **age**, not count.
