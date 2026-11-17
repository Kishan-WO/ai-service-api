# Q6. What is json.dumps?

`json.dumps()` converts a Python object into a **JSON-formatted string** ("dump to string").

```python
import json
data = {"name": "Alice", "age": 30, "active": True, "tags": ["a", "b"], "manager": None}
print(json.dumps(data))
# {"name": "Alice", "age": 30, "active": true, "tags": ["a", "b"], "manager": null}
```

| Python | JSON |
|---|---|
| `dict` | object `{}` |
| `list`, `tuple` | array `[]` |
| `str` | string |
| `int`, `float` | number |
| `True` / `False` | `true` / `false` |
| `None` | `null` |

## Useful options
```python
json.dumps(data, indent=2)            # pretty print
json.dumps(data, sort_keys=True)      # sort keys
json.dumps(data, ensure_ascii=False)  # keep non-ASCII as-is
json.dumps(data, default=str)         # fallback for datetime etc.
```

## Related
- `json.dumps(obj)`: object → JSON **string**
- `json.loads(s)`: JSON string → object
- `json.dump(obj, file)`: object → file
- `json.load(file)`: file → object

## Common error
```python
json.dumps({"time": datetime.now()})
# TypeError: Object of type datetime is not JSON serializable
```
Fix with `default=str` or a custom function.

## In logging
`json.dumps` is often used for **structured JSON logs**:
```python
print(json.dumps({"level": "INFO", "message": "User logged in", "user_id": 42}))
```
