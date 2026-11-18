# Q43. What is `StrictUndefined`?

**What I asked:** "explain strict undefined again"

**Where it is:** `src/ai_service/services/prompt_registry.py`
```python
from jinja2 import Environment, StrictUndefined

_env = Environment(undefined=StrictUndefined)
```

---

## The short answer
`StrictUndefined` makes Jinja **raise an error** when a template uses a variable that was not given a value. Without it, Jinja quietly puts an **empty string** in its place.

## The problem
The template in `prompts/classify_query/v1.md` has a variable:
```
<message>
{{ message }}
</message>
```
Now the code forgets to pass `message`, or spells it wrong:
```python
p.render(mesage="fees kitni hai?")    # typo: mesage
```

| Setting | What `render` gives |
|---|---|
| default Jinja (no `StrictUndefined`) | the prompt with an **empty message**: `<message>\n\n</message>` |
| with `StrictUndefined` | an error: `jinja2.exceptions.UndefinedError: 'message' is undefined` |

## Why the default is dangerous for prompts
The default case does **not crash**. The program sends a prompt with no student text to the model. The model still answers (probably something made up), and the answer is stored, logged and counted in the accuracy. Nothing tells me the prompt was broken, so a bug like this can sit in my measurements for days.

With `StrictUndefined` the same mistake **stops at once**, on the line that called `render`, with the missing variable's name in the message.

## What `Environment(undefined=...)` means
`Environment` is Jinja's settings object. The `undefined=` option says what to do with a missing variable. `StrictUndefined` means "raise an error". Every prompt rendered through `_env` follows that rule.

## The other direction
An **extra** variable that the template does not use is fine; Jinja ignores it:
```python
p.render(message="hi", extra="x")    # works
```
`StrictUndefined` only protects against **missing** variables. A typo in the name I pass (`mesage=`) shows up as a missing `message`, so it is caught too.

## Check it in the REPL (`uv run python`)
```python
from ai_service.services.prompt_registry import get_prompt
p = get_prompt("classify_query", "v1")
p.render()                      # error: 'message' is undefined
p.render(mesage="x")            # the same error: the typo is caught
p.render(message="x")           # works
```

## Quick check
- What does Jinja put in place of a missing variable by default?
- Why is that worse than an error for a prompt?
- Does `StrictUndefined` complain about an extra variable?
