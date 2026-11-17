# Day 5: questions and answers

Questions about `/chat` and `/extract`, arranged **in implementation order**: data model, the LLM interface, saving messages, streaming and disconnects. The `Q` number in a title is the order in which I asked it.

## Data model and the LLM interface (tasks 1 and 2)

| # | Question | File |
|---|---|---|
| 01 | Q23. Meaning of `cascade` in a relationship | [01-cascade.md](01-cascade.md) |
| 02 | Q24. What is `Protocol`, and what does dataclass `frozen` mean? | [02-protocol-frozen-dataclass.md](02-protocol-frozen-dataclass.md) |
| 03 | Q25. Explain `scalars` and `*scope` | [03-scalars-and-scope.md](03-scalars-and-scope.md) |

## Saving messages and streaming the answer (tasks 2 and 3)

| # | Question | File |
|---|---|---|
| 04 | Q26. Explain the session logic in `start_turn` and `save_assistant_message` | [04-start-turn-save-assistant.md](04-start-turn-save-assistant.md) |
| 05 | Q27. Why `session.execute` (not explained before)? | [05-why-session-execute.md](05-why-session-execute.md) |
| 06 | Q28. What is `anext()`? | [06-anext.md](06-anext.md) |
| 07 | Q29. What is `events`? (in the chat streaming code) | [07-events.md](07-events.md) |
| 08 | Q30. What is anyio? | [08-anyio.md](08-anyio.md) |

## Reading the code, `.env`, `/extract` samples and more (all tasks)

| # | Question | File |
|---|---|---|
| 09 | Day 5: questions I asked while reading the code, and the answers | [09-my-questions-while-reading-the-code.md](09-my-questions-while-reading-the-code.md) |

File 09 is one note with several short questions and answers (the index `__table_args__`, `pass` vs `...`, `_as_params`, which model, free-tier limits, the conversation id, `.env` variables, `/extract` samples).
