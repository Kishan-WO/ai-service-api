# Day 6: questions and answers

Arranged **in implementation order**. Q31 to Q35 came from my saved question list; Q36 to Q42 are the questions of 2026-11-17. Some questions have **two answers** (Q33 and Q36 are both about `_prime`; Q34 and Q37 to Q40 both cover the rate limiter), so read the later one for the current code.

## Task 1: the `LLMClient`, its errors and adapters

| # | Question | File |
|---|---|---|
| 01 | Q31. How is `RateLimitedError` used, and how do parent constructor params get passed? | [01-llmerror-ratelimited.md](01-llmerror-ratelimited.md) |
| 02 | Q32. Explain `response_format` | [02-response-format.md](02-response-format.md) |

## Tasks 1 to 3: how the layers (accounting, limits, retry, fallback) are stacked

| # | Question | File |
|---|---|---|
| 03 | Q42. How were the accounting, cost, retry and rate-limit layers added on the default client? | [03-how-the-client-layers-are-stacked.md](03-how-the-client-layers-are-stacked.md) |

## Task 3: retry and fallback on streams (`_prime`)

| # | Question | File |
|---|---|---|
| 04 | Q33. Meaning of `_prime` | [04-prime.md](04-prime.md) |
| 05 | Q36. What is the purpose of `_prime`? (second answer: how the retry and fallback layers use it) | [05-prime-and-stream-retry.md](05-prime-and-stream-retry.md) |

## Task 3: limits (`RateLimiter`, `deque`, `LimitedClient`, the lock)

| # | Question | File |
|---|---|---|
| 06 | Q34. Explain the `RateLimiter` class | [06-ratelimiter.md](06-ratelimiter.md) |
| 07 | Q35. Why use `deque`? | [07-deque.md](07-deque.md) |
| 08 | Q37 to Q40. `LimitedClient`, and the `asyncio.Lock` in the rate limiter | [08-limited-client-and-the-rate-limiter-lock.md](08-limited-client-and-the-rate-limiter-lock.md) |

## Python used in these layers

| # | Question | File |
|---|---|---|
| 09 | Q41. What is `cls`? | [09-what-is-cls.md](09-what-is-cls.md) |

Line-by-line explanations of every Day 6 source file are in [`../explanation/`](../explanation/README.md).
