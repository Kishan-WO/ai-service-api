# Q32. Explain `response_format`

```python
response = await self._client.chat.completions.create(
    model=self.model,
    messages=_params(request.messages),
    temperature=0,
    max_tokens=request.max_tokens or self._max_output_tokens,
    response_format=cast(Any, {
        "type": "json_schema",
        "json_schema": {"name": schema_name, "schema": schema, "strict": True},
    }),
)
```

`response_format` tells the model to **return JSON conforming to a schema** (**structured outputs**).

## The pieces
- **`"type": "json_schema"`**: alternatives `"text"` (default), `"json_object"` (valid JSON, no shape guarantee).
- **`name`**: label for the schema.
- **`schema`**: JSON Schema (fields, types, required, enums).
- **`strict: True`**: output constrained to follow the schema exactly.

## Example
```python
schema = {
    "type": "object",
    "properties": {
        "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
        "confidence": {"type": "number"},
    },
    "required": ["sentiment", "confidence"],
    "additionalProperties": False,
}
data = json.loads(response.choices[0].message.content)
# or Sentiment.model_validate_json(...)
```
`schema` can come from `Sentiment.model_json_schema()`.

## Strict mode rules (OpenAI)
- every object needs `"additionalProperties": False`
- **all** properties in `required` (optional = union with `null`)
- some keywords may be unsupported
Violations → 400.

## Why `cast(Any, ...)`
No runtime effect; silences the type checker.

## Other arguments
- `temperature=0`: minimal randomness.
- `max_tokens=...`: too small a limit can cut JSON off; check `finish_reason == "length"`.

## Things to know
- Strict guarantees **shape**, not **correctness**.
- The model can **refuse**: `message.refusal` set, `content` may be `None`.
- This call is non-streaming (`create(...)` without `stream=True`).
- Other providers have equivalents (Anthropic: tool use / its structured output feature).
