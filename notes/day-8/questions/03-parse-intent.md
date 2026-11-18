# Q46. What does `_parse_intent` do?

**What I asked:** (pasted the function) "explain"

**Where it is:** `src/ai_service/services/router_service.py`
```python
def _parse_intent(raw: str) -> Intent:
    m = _LABEL_RE.search(raw)
    if m:
        label = m.group(1).lower()
        if label in KNOWN_INTENTS:
            return label
    stripped = raw.strip().lower()
    if stripped in KNOWN_INTENTS:
        return stripped
    return "unclear"
```

## The short answer
It turns the classifier's raw reply into one of the intent labels. Anything it cannot read safely becomes `unclear`, which sends the request to the large model.

## Step by step
1. **`CATEGORY: <label>`.** `_LABEL_RE` matches `CATEGORY:` followed by one of the six known labels, ignoring case; the `\b` stops a partial match such as `feesXYZ`. If it matches, the label is lowercased and checked against `KNOWN_INTENTS` once more as a safety net. This format belongs to the earlier `classify_query` v4, which wrote `CATEGORY: fees` after its reasoning.
2. **The bare label.** The current prompt (v5) replies with one word. The regex finds nothing, so the text is stripped, lowercased and compared with the known labels. `"fees\n"` and `" Fees "` both work.
3. **Everything else is `unclear`:** the new `unclear` label, an empty reply, a made-up label such as `billing`, or a sentence such as "I think this is about fees".

## Examples
| Model reply | Result |
|---|---|
| `fees` | `fees` |
| `Fees\n` | `fees` |
| `CATEGORY: schedule` | `schedule` |
| `unclear` | `unclear` |
| `billing` | `unclear` |
| `I think it is fees` | `unclear` |

The last row is the price of being strict: a chatty reply that contains the right label is still escalated. That costs more but never gives a wrong specialised answer, and with `max_tokens=20` the model has little room to be chatty.
