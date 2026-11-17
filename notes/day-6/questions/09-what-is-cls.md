# Q41. What is `cls`?

**What I asked:** "what is cls ?"

---

## The short answer
`cls` is **the class itself**. It is the first parameter of a method marked `@classmethod`, the same way `self` is the first parameter of a normal method.

| Name | Refers to | Used in |
|---|---|---|
| `self` | one object (an instance) | normal methods |
| `cls` | the class (the blueprint) | `@classmethod` methods |

Neither is a Python keyword. They are **conventions** that every Python programmer follows.

## The three kinds of method
```python
class Example:
    def normal(self): ...           # needs an object: self = that object
    @classmethod
    def factory(cls): ...           # needs only the class: cls = the class
    @staticmethod
    def helper(x): ...              # needs neither: a plain function stored inside the class
```

## A small example
```python
class Dog:
    def __init__(self, name):
        self.name = name

    @classmethod
    def puppy(cls):
        return cls("Puppy")      # the same as Dog("Puppy")

d = Dog.puppy()    # no Dog object needed first
print(d.name)      # Puppy
```
`Dog.puppy()` passes `Dog` as `cls`, so `cls("Puppy")` creates a new `Dog`.

## Example 1 from this project: a factory method
`RetryPolicy` in `services/llm_wrappers.py`:
```python
@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 20.0
    total_seconds: float = 90.0

    @classmethod
    def from_settings(cls, settings: Settings) -> RetryPolicy:
        return cls(
            attempts=settings.LLM_RETRY_ATTEMPTS,
            base_delay=settings.LLM_RETRY_BASE_DELAY_SECONDS,
            max_delay=settings.LLM_RETRY_MAX_DELAY_SECONDS,
            total_seconds=settings.LLM_RETRY_TOTAL_SECONDS,
        )
```
- Called on the class: `RetryPolicy.from_settings(settings)`. The registry uses it in `llm.py`.
- `cls(...)` means `RetryPolicy(...)`: it builds and returns a new object.
- This is a **factory method**: another way to create an object. In Express/JavaScript terms it is like a `static` method that returns `new ClassName(...)`.
- If a subclass of `RetryPolicy` is made later, `cls` is the **subclass**, so the factory builds the right type. Writing `RetryPolicy(...)` directly would not do that.

## Example 2 from this project: Pydantic validators
`schemas/extract.py` and `core/config.py`:
```python
@field_validator("phone")
@classmethod
def _looks_like_a_phone(cls, value: str | None) -> str | None:
    ...
```
Pydantic **requires** validators to be class methods, because it runs them while it is still deciding whether the data is valid, **before any object exists**. There is no `self` yet. `cls` is only there to satisfy the required signature; these validators never use it. The same is true of `blank_means_not_set` in `Settings` and `validate_database_url`.

## When to use which
- Need the object's own data (`self.name`)? Normal method with `self`.
- Need to create objects in another way, or work with class-level data? `@classmethod` with `cls`.
- Just a helper that needs neither? `@staticmethod`, or a plain function outside the class.

## Quick check
- What does `cls("Puppy")` do inside `Dog.puppy()`?
- Why do Pydantic validators take `cls` and not `self`?
- Why is `cls(...)` better than writing the class name inside a factory method?
