# Q13. Explain the expiry block in `create_access_token`

```python
if expires_delta:
    expire = now + expires_delta
else:
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

to_encode.update({"exp": expire, "iat": now})
```

Decides **when the token expires**, then stamps expiry and issue time into the payload.

## Part 1: choosing expiry
- If `expires_delta` is provided, expiry is `now + expires_delta`.
- Otherwise the settings default (e.g. 30 minutes).
- `now` is timezone-aware UTC.

```python
create_access_token({"sub": "42"})                                   # default
create_access_token({"sub": "42"}, expires_delta=timedelta(days=7))  # custom
```
Useful for short-lived tokens (password reset) or longer ones (remember me).

## Part 2: claims
`to_encode.update({"exp": expire, "iat": now})` adds standard JWT claims:

| Claim | Meaning |
|---|---|
| `exp` | Expiration time: reject after this |
| `iat` | Issued at |

`jwt.encode(...)` converts these datetimes to **Unix timestamps** automatically.

## Why it matters
- `jwt.decode(...)` checks `exp` automatically (`ExpiredSignatureError`).
- `iat` helps auditing and invalidation (e.g. reject tokens issued before a password change).

## Why `data.copy()`
`update(...)` modifies a copy, not the caller's dict.

## Small note
`if expires_delta:` is falsy for `timedelta(0)` too. Use `if expires_delta is not None:` to avoid that edge case.
