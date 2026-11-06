# What I asked the IDE chatbot to explain (Day 3, ai-service)

Source: my chat with the Antigravity IDE chatbot while building `ai-service`, 4 and 5 Nov 2026 (46 prompts). 29 of them asked for an explanation; the rest were instructions, listed at the end. Line numbers are the ones that were true at that time.

## Topics at a glance
| Topic | Questions |
|---|---|
| Config and settings | 3 |
| Python language and packages | 4 |
| Database and services | 7 |
| Caching and Redis | 1 |
| App, middleware, error handlers and dependencies | 9 |
| Running, Swagger and streaming | 5 |

---

## 1. Config and settings
| Date, time | What I asked | Code |
|---|---|---|
| 04-11 13:13 | Why did you set default values in `config.py`? | `core/config.py` |
| 04-11 13:28 | What does this line do? (the `model_config = SettingsConfigDict(...)` block) | `core/config.py` L56 |
| 04-11 13:29 | What does this do? (`@lru_cache` on `get_settings()`) | `core/config.py` L60-L63 |

## 2. Python language and packages
| Date, time | What I asked | Code |
|---|---|---|
| 04-11 13:26 | What is the meaning of `__all__`? | `core/__init__.py` L12-L20 |
| 04-11 14:52 | What is the meaning of this? (the `# noqa: F401` comment on the model import) | `alembic/env.py` |
| 04-11 14:54 | How is it defined that the import name will be `ai_service`? | the package folder vs `pyproject.toml` |
| 04-11 18:24 | Explain the meaning of `*` in this function signature | `services/auth_service.py` L25 |

## 3. Database and services
| Date, time | What I asked | Code |
|---|---|---|
| 04-11 13:18 | Why did you use a test database? | tests setup |
| 04-11 13:35 | Explain this code, I am from a JS background (the `TimestampMixin`) | `db/base.py` L24-L37 |
| 04-11 13:39 | Explain this (the async engine and session factory) | `db/session.py` L16-L29 |
| 04-11 18:58 | Explain this (`session.scalar(select(User.id).where(...))`) | `services/auth_service.py` L28 |
| 05-11 14:42 | Why did you use `session.rollback` and `commit` in this service but not in the other services? | `services/auth_service.py` L25-L39 |
| 05-11 14:46 | Explain (`PdfReader(io.BytesIO(data))`) | `services/document_service.py` L46 |
| 05-11 14:51 | Explain this (`await asyncio.to_thread(extract_text, suffix, data)`) | `services/document_service.py` L75 |

## 4. Caching and Redis
| Date, time | What I asked | Code |
|---|---|---|
| 04-11 13:16 | Is adding a cache told in the Day 3 plan? | Day 3 plan |

## 5. App, middleware, error handlers and dependencies
| Date, time | What I asked | Code |
|---|---|---|
| 04-11 16:49 | Explain this (the `lifespan` function) | `main.py` L21-L29 |
| 04-11 17:04 | What is this? (`app.add_middleware(RequestContextMiddleware)`) | `main.py` L47 |
| 04-11 17:11 | In which order will a request be passed to the route? | whole app |
| 04-11 17:15 | Explain this (the `scope["type"] != "http"` check in `__call__`) | `core/middlewares.py` L49-L52 |
| 04-11 17:21 | Explain this (`send_with_headers`) | `core/middlewares.py` L63-L70 |
| 04-11 17:25 | Explain this (`await self.app(scope, receive, send_with_headers)` in a `try/finally`) | `core/middlewares.py` L74 |
| 04-11 17:29 | Where is this used? (`register_error_handlers`) | `core/middlewares.py` L161-L165 |
| 04-11 17:30 | The global error handler should be last, so why is it before the routes? | `main.py` |
| 04-11 17:42 | Explain what is happening here, but skip the imports | `api/deps.py` L1-L62 |

## 6. Running, Swagger and streaming
| Date, time | What I asked | Code |
|---|---|---|
| 05-11 15:15 | How to run this project? | project |
| 05-11 15:23 | How can I authorise in Swagger? It doesn't keep my access token. What is this popup and how do I use it? | Swagger UI |
| 05-11 15:38 | Swagger shows "loading" for a streaming response and displays everything only at the end | `GET /stream/demo` |
| 05-11 15:49 | Explain `stream.py` line by line: everything except the route first, the route next time | `api/v1/stream.py` |
| 05-11 16:02 | Can you give me a real example that calls real AI models? | streaming code |

---

## Where my own notes already cover these
| Questions | Note |
|---|---|
| Order of a request, the middleware lines, `try/finally` around the app | `notes/request-response-cycle.md` |
| Error handler placement, handlers vs middleware order | `notes/exception-handlers-vs-express.md` |
| Why services commit and roll back themselves | `gotchas.md` ("Commit in the service") and `decisions.md` (item 7) |
| `asyncio.to_thread` and blocking the event loop | Day 2: `learning/12.blocking-loop-to-thread-httpx.md` |
| `**kwargs`, `*args`, and the `ParamSpec` stars | Day 2: `Notes/paramspec-and-double-star.md` |

## Still open
- The **route** part of `stream.py` (I said "next time we will take the route").
- A real call to an AI model from the streaming endpoint (the example was asked for, not built yet).

---

## Other prompts in the same chat (instructions, not questions)
| Date, time | Prompt |
|---|---|
| 04-11 12:50 | Let's see the plan for all the days |
| 04-11 12:50 | What work do we have in Day 3? |
| 04-11 12:54 | Day 1 and 2 are done; make a step-by-step plan for Day 3 and give it for review |
| 04-11 12:57 | Start step 1 |
| 04-11 13:08 | Step 2 |
| 04-11 13:14 | Remove the defaults and add validation on env values, so wrong values give an error |
| 04-11 13:18 | Remove Redis from the application for now |
| 04-11 13:21 | It's okay, go to the next step |
| 04-11 13:24 | Tell me the Alembic commands and what to do manually |
| 04-11 14:51 | Let me instruct you to configure Alembic |
| 04-11 15:05 | Check whether the current `env.py` is okay |
| 04-11 15:06 | Done it |
| 04-11 15:07 | Yes, create the Docker Compose file |
| 05-11 15:54 | Ok, next |
| 05-11 16:07 | I think everything is done from Day 3 (sent twice) |
| 05-11 16:13 | I added `git init` in the `ai-eng` folder; check whether we missed anything to add in this directory |

---
Notes written from these questions: see `ai-help-topics-index.md` (topics grouped by the day of the learning plan).
