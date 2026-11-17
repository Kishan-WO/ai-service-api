# Q42. How were the accounting, cost, retry and rate-limit layers added on the default client?

**What I asked:** "how u have added clients layers like accounting, cost, retry, rate limite etc.. added on default client"

---

## The short answer
I **wrapped** the plain client in layers, one inside the next (the **decorator pattern**, similar to Express middleware). Each layer is itself an `LLMClient`, so any layer can be put around any other. The registry builds the stack in `services/llm.py`.

## 1. What is the "default client"?
The **adapter** that talks to the provider. It has the three methods every client must have: `generate`, `generate_structured` and `stream`.
```python
OpenAICompatProvider(client, "gemini-3.1-flash-lite", 2000, backend="hosted")
```
On its own it only makes the call. It has no retry, no limits and no cost log.

## 2. What a layer looks like
Every layer follows the same rules:
- the constructor takes **`inner`**, the client to wrap;
- it has the **same three methods** and the same `backend` and `model`;
- each method does its own small job, then calls `self._inner....`.

`LimitedClient`, cut down to the pattern:
```python
class LimitedClient:
    def __init__(self, inner, *, max_concurrency, per_minute=0):
        self._inner = inner              # the client it wraps
        self.backend = inner.backend
        self.model = inner.model

    async def generate(self, request):
        async with self._semaphore:      # my job: wait for a free slot
            await self._start()
            return await self._inner.generate(request)   # then pass the call on
```
`RetryingClient`, `AccountingClient` and `FallbackClient` have the same shape with a different job in the middle.

| Layer | File | Its job |
|---|---|---|
| `AccountingClient` | `llm_accounting.py` | time the call, compute the cost (`llm_cost.py`), write one log line and one `llm_calls` row |
| `LimitedClient` | `llm_wrappers.py` | at most N calls at once and M per minute |
| `RetryingClient` | `llm_wrappers.py` | retry temporary errors with backoff and jitter |
| `FallbackClient` | `llm_wrappers.py` | if the backend still fails, ask the next one |

**Cost** is not a layer of its own: `compute_cost()` is a plain function that `AccountingClient` calls for every call, using the price table in the settings.

## 3. How the registry stacks them
`SettingsLLMRegistry._stack` in `services/llm.py`:
```python
client = AccountingClient(self._adapter(backend), prices=s.LLM_PRICES, recorder=self._recorder)
client = LimitedClient(client, max_concurrency=s.LLM_MAX_CONCURRENCY, per_minute=...)
self._stacks[backend] = RetryingClient(client, RetryPolicy.from_settings(s))
```
Each line wraps the result of the line before. Then `_route` adds the last layer:
```python
return FallbackClient([primary, self._stack(second)])
```
Read it **from the inside out**:
```
adapter                        makes the HTTP call
AccountingClient(adapter)      + logs every call and saves a row
LimitedClient(...)             + waits for a free slot and the per-minute limit
RetryingClient(...)            + retries temporary errors
FallbackClient([...])          + tries the second backend if all retries fail
```
The route never builds any of this. It calls `llm.get(body.backend)` and uses the outer object.

## 4. How one call travels
```
FallbackClient.generate
  RetryingClient.generate          (loop: try, fail, wait, try again)
    LimitedClient.generate         (wait for a slot, then go on)
      AccountingClient.generate    (start the timer)
        adapter.generate           (HTTP call to Gemini)
      AccountingClient             (stop the timer, compute the cost, write the log and the row)
    LimitedClient                  (release the slot)
  RetryingClient                   (on an error: sleep, loop again from the top)
FallbackClient                     (on a final error: try the second backend)
```
The call goes **in** through the layers; the answer or the error comes back **out** in reverse order.

## 5. Why this order
| Choice | Reason |
|---|---|
| Accounting is innermost | it sits next to the provider, so **every real HTTP call gets its own row**, including each retry (a request that fails twice and then works makes three rows) |
| The limiter is inside retry | each retry attempt has to pass the limiter too, so a burst of retries cannot break the per-minute limit |
| Retry is outside the limiter | the slot is released while the retry layer sleeps, so a waiting request does not block others |
| Fallback is outermost | it moves on only after **all** retries on the first backend have failed |

## 6. Why this design
- Each layer is small, has **one job**, and is tested **alone** with a scripted fake client and a fake clock (`tests/test_llm_wrappers.py`, `test_llm_accounting.py`).
- Adding or removing a layer is **one line** in `_stack`. The routes do not change, because they only know "something with `generate`, `generate_structured` and `stream`".
- It works because `LLMClient` is a **`Protocol`** (structural typing): a layer does not inherit from anything; having the right methods is enough. The adapters, all the layers and the test fakes fit the same type.
- The SDKs' own retries are switched off (`max_retries=0`), so only the retry layer retries and the calls do not multiply (3 x 3 = 9).

## 7. Real proof from the runs
- With the hosted URL on a dead port and `LLM_FALLBACK_BACKEND=local`, the log showed the layers working in order: `llm structured error` (accounting, one per try), `llm retry 2/3 ... waiting 0.5 s` (retry), then `llm fallback: hosted failed, trying local` (fallback), then `llm structured ok: local gemma3:270m` (accounting again).
- A burst of 25 requests: the limiter and the retry layer together turned 6 rate-limit errors into 25 answers.

Longer walkthroughs: `../explanation/06-llm_wrappers.md`, `../explanation/05-llm_accounting_and_cost.md`, `../explanation/07-llm_registry.md`.

## Quick check
- What three things must a class have to be a layer in this stack?
- Why does accounting sit innermost and fallback outermost?
- Which line of `_stack` would you change to add a new layer?
- Why is cost not a layer of its own?
