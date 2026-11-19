# AI Service frontend

A React (Vite, plain JavaScript) interface for the `ai-service` FastAPI backend.

| Page | Backend endpoint | What it does |
|---|---|---|
| Sign in / Create account | `POST /auth/login`, `/auth/register`, `GET /auth/me` | a JWT is kept in `localStorage`; a 401 signs the user out |
| Chat | `POST /chat` (SSE), `GET/DELETE /chat/conversations` | streams the answer token by token, a Stop button cancels it, past conversations on the left |
| Documents | `/documents` upload, list, view, delete | `.txt`, `.md`, `.pdf`; private to the organisation |
| Summarise | `POST /summarise` | pick documents, summarise in parallel, see the overview, per-document summaries and any failed ones |
| Extract | `POST /extract` | messy enquiry text to clean fields, with attempts, tokens and latency |
| Router | `POST /route` | the intent, who answered, timings and tokens |

## Run it with Docker (the whole stack)
From the `ai-service` folder (the one with `docker-compose.yml`):
```
docker compose up -d --build
```
Open http://localhost:3000. nginx serves the built site and forwards `/api` to the `api`
container, so there is nothing to configure.

## Run it for development

1. Start the API (default `http://localhost:8000`).
2. In this folder:
   ```
   npm install
   npm run dev
   ```
3. Open http://localhost:5173 and create an account.

The browser calls `/api/...` on the Vite dev server, which forwards it to the API (see
`vite.config.js`). The browser sees one origin, so **no CORS setting is needed** in the API's `.env`.
If the API runs elsewhere, set `VITE_API_TARGET`:

```
VITE_API_TARGET=http://localhost:8001 npm run dev
```

## Layout
```
src/
  api/client.js           every API call; error envelope -> ApiError; SSE reader for /chat
  auth/AuthContext.jsx    token, current user, sign in / up / out
  components/             Layout, ProtectedRoute, shared pieces (ErrorBox, BackendSelect, ...)
  pages/                  Login, Chat, Documents, Summarise, Extract, RouterPlayground
  index.css               all styles (light and dark by the system setting)
```

## Notes
- Chat uses `fetch` and reads the response stream by hand, because `EventSource` cannot send a POST
  body or an `Authorization` header. Events: `start`, `token`, `done`, `error`.
- For a production build run `npm run build` and serve `dist/` behind the same host as the API (or
  add the site's origin to the API's `CORS_ORIGINS`).
