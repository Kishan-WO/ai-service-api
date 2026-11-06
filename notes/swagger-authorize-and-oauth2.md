# Swagger "Authorize" and the OAuth2 password flow

Question: Swagger shows a login popup and does not keep my access token. What is the popup, and how do I use it?

## 1. Why the popup exists
`/docs` is the interactive page FastAPI builds from the code. It shows an **Authorize** button and a padlock on protected endpoints because `deps.py` declares:

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)
```
That line tells Swagger: "this API uses the OAuth2 **password flow**; get a token by sending a username and password to `tokenUrl`."

## 2. Using it, step by step
1. **Register** once: `POST /api/v1/auth/register` with email, password (8+ characters) and tenant name. Or skip this if the account already exists.
2. Click **Authorize** (top right).
3. In the popup fill in:
   | Field | Value |
   |---|---|
   | `username` | the account's **email** (the form field is called "username" by the OAuth2 standard) |
   | `password` | the account password |
   | `client_id`, `client_secret` | leave empty |
4. Click **Authorize**, then **Close**.
5. The padlocks now show as locked. Call `GET /api/v1/auth/me`: it works without pasting anything.

What happens behind the scenes: Swagger sends a **form** (`application/x-www-form-urlencoded`) to `POST /api/v1/auth/token`, takes `access_token` from the reply, and adds `Authorization: Bearer <token>` to every request it sends.

## 3. Why there are two login endpoints
| Endpoint | Body | Used by |
|---|---|---|
| `POST /auth/login` | JSON `{"email", "password"}` | Normal clients and tests |
| `POST /auth/token` | OAuth2 **form** (`username`, `password`) | The Swagger Authorize popup |

Both call the same `auth_service.authenticate` and return the same token response.

## 4. "It doesn't store my token"
Swagger UI keeps the authorization **in memory for that page**. A browser refresh, or opening `/docs` in a new tab, clears it and I must authorize again.

FastAPI can ask Swagger UI to remember it in the browser:
```python
app = FastAPI(..., swagger_ui_parameters={"persistAuthorization": True})
```
This is an option, not turned on in this project. It stores the token in the browser's local storage, which is convenient for development and a poor idea for a shared machine.

## 5. Token lifetime
The token expires after `ACCESS_TOKEN_EXPIRE_MINUTES` (1440 = 24 hours by default). After that, protected calls return 401 and I log in again.

## 6. Checking from the command line
```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
     -d "username=me@example.com&password=correct-horse-battery"
```
```bash
curl http://localhost:8000/api/v1/auth/me -H "Authorization: Bearer <access_token>"
```

## 7. Why the "username" is an email
The OAuth2 password form always has the field names `username` and `password`. This project simply treats `username` as the email address.

## Common mistakes
| Mistake | What happens |
|---|---|
| Typing a name in `username` | 401 `INVALID_CREDENTIALS` (it must be the email) |
| Filling `client_id` / `client_secret` | Not needed; harmless but pointless |
| Refreshing the page and wondering where the token went | Authorize again, or enable `persistAuthorization` |
| Using the JSON `/login` from the popup | The popup sends a form; it must use `/token` |
| An expired token | 401; log in again |

## Quick check
- Which line in the code makes the Authorize button appear?
- What does the popup send, and to which endpoint?
- Why are there both `/login` and `/token`?
- Why does Swagger forget the token on refresh, and how can it be changed?
