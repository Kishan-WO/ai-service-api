# Q12. What is ConfigDict()?

`ConfigDict` is a Pydantic v2 typed dict used to **configure model behavior** (validation, serialization, extra fields...).

```python
from pydantic import BaseModel, ConfigDict

class User(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)
    name: str
    age: int
```

## Common options
```python
ConfigDict(
    from_attributes=True,        # create from ORM objects
    str_strip_whitespace=True,   # trim strings
    extra="forbid",              # error on unknown fields ("ignore" default, "allow")
    frozen=True,                 # immutable + hashable
    populate_by_name=True,       # allow field name even with alias
    validate_assignment=True,    # re-validate on assignment
    use_enum_values=True,        # store enum values
)
```

## Most common in FastAPI
```python
class UserOut(BaseModel):
    id: int
    email: str
    model_config = ConfigDict(from_attributes=True)
```
Lets you return a SQLAlchemy object and have it converted. In v1 this was `orm_mode = True`.

## Relation to settings
`SettingsConfigDict` is a **subclass of `ConfigDict`** with extras like `env_file`, `env_prefix`, `env_nested_delimiter`.

## Old vs new
```python
# v1
class Config:
    orm_mode = True
# v2
model_config = ConfigDict(from_attributes=True)
```
Inner `class Config` still works in v2 but is deprecated. A plain dict also works, but `ConfigDict(...)` gives editor checking.
