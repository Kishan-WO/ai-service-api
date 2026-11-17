# Q14. What is `options` in `jwt.decode`?

```python
return jwt.decode(
    token,
    settings.SECRET_KEY,
    algorithms=[settings.ALGORITHM],
    options={"require": ["exp", "iat", "sub", "tenant_id"]},
)
```

`options` holds **extra validation rules** (PyJWT). `{"require": [...]}` means these claims **must be present**, or decoding fails.

## Why
By default PyJWT validates `exp` only **if it exists**; a token with no `exp` would never expire. `require` rejects tokens missing any listed claim (`jwt.MissingRequiredClaimError`, a subclass of `jwt.PyJWTError`).

| Claim | Why required |
|---|---|
| `exp` | token must expire |
| `iat` | records issue time |
| `sub` | identifies the user |
| `tenant_id` | custom claim for multi-tenancy |

This matches `create_access_token`, so decode enforces the same contract and avoids later `KeyError`s.

## `require` only checks presence
Value checks (e.g. valid tenant) must be done in your own code.

## Other options
```python
options={
    "verify_signature": True,  # never False in production
    "verify_exp": True,
    "verify_iat": True,
    "verify_aud": True,
    "require": ["exp", "sub"],
}
```

## Why `algorithms=[...]` is a list
A whitelist of allowed algorithms (e.g. `"HS256"`); prevents algorithm-confusion attacks such as `none`.
