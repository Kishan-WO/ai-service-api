# Q24. What is `Protocol`, and what does dataclass `frozen` mean?

## Protocol
`Protocol` (from `typing`) defines a **structural interface**: any class with the right methods/attributes matches **without inheriting** ("static duck typing").
```python
from typing import Protocol

class LLMProvider(Protocol):
    async def generate(self, prompt: str) -> str: ...

class OpenAIProvider:
    async def generate(self, prompt: str) -> str: ...

class AnthropicProvider:
    async def generate(self, prompt: str) -> str: ...

async def answer(provider: LLMProvider, question: str) -> str:
    return await provider.generate(question)
```
### Why
- **Decoupling** from specific vendor classes.
- **Easy testing**: fake class with the same method.
- **Swappable implementations.**

### Things to know
- `...` body = no implementation, just a signature.
- Checked by static type checkers (mypy, pyright), not at runtime.
- `@runtime_checkable` allows `isinstance()` (names only, not signatures).
- ABC needs explicit inheritance; Protocol needs only matching shape.

## `@dataclass(frozen=True)`
Makes instances **immutable**.
```python
@dataclass(frozen=True)
class LLMResponse:
    text: str
    tokens: int

r = LLMResponse("hello", 5)
r.text = "x"   # FrozenInstanceError
```
### What you get
- Immutability (`FrozenInstanceError` on assign/delete).
- **Hashable** (with default `eq=True`): usable in sets / dict keys.
- Safety for config, results, value objects.

Create modified copies with `dataclasses.replace(r, text="changed")`.

### Caveat
Frozen is **shallow**: a mutable field (like a `list`) can still be mutated. Use `tuple`.

`@dataclass(frozen=True, slots=True)` also makes instances smaller/faster.
