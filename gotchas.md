# Gotchas and Surprises

Records unexpected behaviors, bugs, and lessons learned during development.

## Day 3: FastAPI Base
- **Passlib vs Pwdlib**: `passlib` uses the deprecated `crypt` module which is completely removed in Python 3.13+. We use `pwdlib[argon2]` which is modern, secure, and officially recommended for FastAPI.
- **Tenant ID Source**: Never accept `tenant_id` from request parameters or body. It must always be decoded from the authenticated user's JWT claim to prevent tenant leakage.
- **Cross-Tenant Status Code**: Accessing another tenant's resource must return `404 Not Found` rather than `403 Forbidden` to prevent resource ID enumeration.
- **Async Database Sessions**: Always use `async_sessionmaker` with `expire_on_commit=False` in async FastAPI dependencies to prevent unexpected attribute refresh queries after transaction commit.

- **Commit in the service, not after `yield`**: with FastAPI 0.162 the exit code of a `yield` dependency runs *after* the response has been sent. I measured it: the order was endpoint returns, response start, response body, dependency exit. A commit placed there means the client can get a 201 before the data is saved, and a failed commit is invisible to it. Services call `session.commit()` themselves; the one in `get_db_session` is now a harmless safety net.
- **Pure ASGI middleware for streaming**: `BaseHTTPMiddleware` wraps the response and complicates streaming and disconnect detection. `RequestContextMiddleware` is a plain ASGI class.
- **Unhandled errors bypass user middleware**: the `Exception` handler runs in Starlette's outermost `ServerErrorMiddleware`, outside my middleware, so it must add `X-Request-ID` itself. In tests, `httpx.ASGITransport` re-raises app exceptions unless `raise_app_exceptions=False`.
- **SQLite in tests needs `StaticPool`**: an in-memory SQLite database is per connection, so without it every new connection sees empty tables.
- **PostgreSQL `text` cannot contain NUL (`\x00`)**: uploads are stripped of NUL characters before saving, otherwise asyncpg raises an error.
- **Client disconnects can arrive as cancellation**: when the client hangs up while the generator is waiting, the server cancels it (`CancelledError`); `request.is_disconnected()` only catches the case where the generator is running. The stream handles and logs both. Seen against the real server: "SSE stream cancelled after 3 of 40 words".
- **Untrusted `X-Request-ID`**: a client-supplied id is only accepted when it is 1 to 64 safe characters; otherwise a new UUID is used (protects logs and headers from injection).
- **Python 3.14 `except A, B:`**: PEP 758 allows listing exception types without parentheses when there is no `as`. `ruff format` rewrites `except (A, B):` that way. It is valid, just unfamiliar.
- **Same message for unknown email and wrong password**, and a dummy hash is verified when the user does not exist, so neither the response nor its timing reveals which emails are registered.
- **Port clashes on Windows**: the host already ran PostgreSQL on 5432 and a Redis container on 6379, so the stack publishes 5433 and 6380.

## Day 5: LLM integration
- **The OpenAI SDK 3.x has its own HTTP library (`httpx2`)**: `respx` patches `httpx` and does not see the SDK's calls, so a mocked test silently made a real connection attempt. Use `httpx2.MockTransport` as the SDK client's `http_client` (see `tests/test_llm_provider.py`). The "provider failure" tests passed by accident at first because a connection error is also an `LLMError`; each failure test now asserts that the fake server received the request.
- **Clean-up in a cancelled stream needs shielding**: when the client drops, the server cancels the generator, and any `await` in its `finally` is cancelled again immediately. The close-upstream and save-reply code runs inside `anyio.CancelScope(shield=True)`; without it the partial answer is never saved.
- **Closing the upstream call is what stops the billing**: leaving the OpenAI `AsyncStream` (`await stream.close()` in a `finally`) makes the provider stop generating. Tokens produced before the close are still billed.
- **`StreamingResponse` + `yield` dependencies**: the session dependency exits after the response is sent, so the stream saves the reply with its own session from `get_session_factory`. In tests that factory is overridden to the in-memory database; forgetting that sends the save to the real database.
- **Gemini sometimes sends the whole answer as one chunk** (small models especially), so a "stream" can contain a single `token` event. Ollama sends word by word.
- **`BigInteger` primary keys do not auto-increment on SQLite**: `BigInteger().with_variant(Integer, "sqlite")` keeps PostgreSQL on `BIGSERIAL` and the tests working.
- **Windows: `os.execvpe` does not replace the process**: a launcher script that used it left an orphaned server. Use `subprocess.call` and run it as a background task.
- **A valid shape is not a correct answer**: the 270M local model returns JSON that passes validation (phone `"python"`, the whole message as the email). Validation catches format, not truth.
- **A route handler is not cancelled when the client leaves before the response starts**: uvicorn only reports the disconnect to code that listens for it (a `StreamingResponse` does, a plain `await` inside the handler does not). Seen live: Gemini took 60 s to send its first event, `curl` gave up at 60 s, and the server still stored the question. `POST /chat` now checks `request.is_disconnected()` right after the first event and, if the client is gone, closes the upstream call and stores nothing (answers `499`).
- **Waiting for the first event means a slow model looks like a dead connection**: the response headers are only sent once the model has started answering, and Gemini's first token ranged from 1 s to over 25 s in my runs (60 s once). That is the price of returning a clean `502` when the provider is down. Clients need a generous timeout; `LLM_TIMEOUT_SECONDS` bounds the wait on the server.
- **The SDK's retries multiply the timeout**: with the default `max_retries=2` and a 60 s timeout, a stuck local model held one `/extract` request for 182 s. (Day 6 replaced `LLM_MAX_RETRIES` with my own retry layer and `max_retries=0` on the SDKs.) A 400-token cap on extraction (an `Enquiry` is about 150 tokens) bring the worst case to about 26 s for the 270M model, and a model that cannot stop writing now ends in `EXTRACTION_FAILED` instead of a timeout.


## Day 6 (found by running it, not by reading the docs)
- **A request held a database connection while it waited for the model**: authentication reads the user in a transaction that stays open until the request ends, so 25 simultaneous `/extract` calls needed 25 connections and the pool has 15. Ten answered `500` (`QueuePool limit of size 5 overflow 10 reached`) while the model was fine. Both routes now call `await session.commit()` right after authentication (it keeps the loaded user, because `expire_on_commit=False`), and a test fails without it. The rule: never hold a database connection across a slow external call.
- **Gemini's 429 has no `retry-after` header**: the wait is in the body, `Please retry in 23.6s.`, which comes back as a JSON **list** (`[{"error": ...}]`). My backoff alone would wait 0.3 to 2 s and burn all the attempts; `map_openai_error` now reads the seconds from the text when the header is missing.
- **The free tier says "quota" for a per-minute limit**: the message is `You exceeded your current quota` even for requests per minute. A daily limit is told apart only by `per day` in the text, so that is what the code looks for before calling a 429 a quota error (not worth retrying) instead of a rate limit.
- **Prompt caching on Gemini only starts above a minimum prompt size, and it caches in chunks**: with a 3.5K-token system prompt nothing was ever cached; with 4.8K tokens turn 2 onward showed `cache_read_tokens` of about 2,030 (about 40% of the prompt) and the cost per turn fell by about a third. The OpenAI-compatible endpoint reports it as `prompt_tokens_details.cached_tokens` and only when there is a hit. Caching is best effort: the first call of a run showed 0.
- **`prompt_tokens` includes the cached part, Anthropic's `input_tokens` does not**: the adapters turn both into one `Usage`, otherwise the cost of a cached request is counted twice on one provider.
- **The SDKs retry on their own** (2 times by default), and so does my retry layer: both are needed to be off in one place. The SDKs are built with `max_retries=0`.
- **`LLM_API_KEY=` in a `.env` file is an empty string, not "unset"**: `SecretStr("")` is not `None`, so the hosted backend looked configured and failed with a 401. A validator turns blank values into `None`.
- **A latency of 56 s in the 50-input report is queueing, not the model**: with 6 requests in flight and a limit of 12 calls per minute, a request waits in my own limiter. The per-call latency in `llm_calls` (about 2 to 4 s) is the model's.
- **A connection to a closed port takes about 2 s to fail on Windows**, so a test of "the provider is down" with three tries takes 6 s before the fallback answers.
- **A negative budget passes the schema**: `"Budget -5000 rupees"` came back as `budget_inr: -5000`. Strict schema mode guarantees the type, not the sense. A `ge=0` on the field is the follow-up.

## Day 7 (found by running it)
- **A test set that every version passes measures nothing**: the first 30 cases (clean, one obvious topic each) gave 29/30 for all four prompt versions, so the "cheapest wins" decision was empty. The harder set (tie cases such as "paid but no access", Hinglish, an injection, a job enquiry) separated v1 (86.7%) from v2 to v4 (100%).
- **A label and the prompt's own definitions must agree**: the prompts listed "batches starting" under `admission` while the test label for "when will the next batch start" was `schedule`; three versions "failed" by obeying their own prompt. Fix the definition or the label before comparing versions.
- **Zero-shot answers are free text**: v1 replied with `**admission**`, `Classification: fees` or a full sentence in 17 to 19 of 30 cases (a bare label in only 11 to 13); the scorer reads the first label word and marks the reply as badly formatted. One reply even started with "Bonjour." because it obeyed the injected instruction.
- **Latency must be read from the accounting layer, not the caller's stopwatch**: with the per-minute limiter a request can wait for its turn, so a caller-side timer showed 30 s p95 for a 1 s call. The script now takes latency from the call record.
- **`LLMRequest` has no `temperature`**: a script that passed one crashed with a `TypeError`; the structured adapter sets 0 itself, and plain `generate` uses the provider's default (answers were identical across two runs anyway).
- **A hand-set `LLM_REQUESTS_PER_MINUTE=12`** keeps a 120-call run under the free tier's 15 per minute; without it the first run hit 429 and waited 30 to 38 s on several calls.

## Day 8 (found by running it)
- **A classifier prompt with no `unclear` label can never escalate**: v2 always returns one of six labels, so "unclear goes to the large model" would have been dead code. Add the label (v5) and test it with requests that should escalate.
- **A greeting rule must match the whole message**: "Hi, I want the eligibility criteria" is an admission question; a rule on the word "hi" sent it to `other`.
- **Thinking tokens hide in `total_tokens`**: with `gemini-3-flash-preview`, `completion_tokens` was 1 while `total_tokens - prompt_tokens` was 41. Cost from `completion_tokens` alone is far too low for a thinking model.
- **`gemma-4-31b-it` through the OpenAI-compatible endpoint** answered with its reasoning as text (`<thought>...</thought>`), reported 0 completion tokens, took 24 s and returned 503 under load. It is not a drop-in "large" model here.
- **A 270M model with a label list collapses to the first label**: `gemma3:270m` answered `admission` for 39 of 60 messages. A reply that is "a valid label" is no confidence signal.
- **Python source written through the shell**: `\b` in a regex arrived as a backspace character and the rule silently matched nothing. Build such characters with `chr(92)` and look at `repr()` of the line.
- **A thinking model can spend the whole `max_tokens` on thinking**: with a cap of 1,000 one `gemini-3-flash-preview` answer used 996 tokens thinking and stopped mid-sentence. Give a thinking model a larger cap than a plain one, and read `finish_reason` (or compare output tokens to the cap) when a reply looks cut.
- **A router adds latency even when it saves money**: classify and answer are two sequential calls, so the median was 4.6 s against 3.8 s for one large call. Report cost and latency together.
- **A free daily quota decides the size of a comparison**: 20 requests a day for the large model meant 14 queries and one run. Say so next to every percentage.
- **A test that depends on a setting must set it**: `LLM_LARGE_MODEL` was empty when I wrote two tests, then `.env` got a value and they failed with `hosted_large` instead of `hosted`. Pin every setting a test relies on.
- **Latency of one live run varies by seconds**: a run with one document less (run C, 5.3 s) was faster than the full run (B, 10.2 s). Compare runs only when the difference is large, or repeat them.
- **`gather` without `return_exceptions` loses the finished results**: the first exception is raised and the other nine summaries are gone; the other calls keep running unseen in the background.
- **LangGraph needs the run's context passed again on resume**: after an interrupt, `ainvoke(None, config, context=deps)` needs the same `context`, otherwise the nodes have no clients.
- **A graph error carries a note, not a new type**: the original exception comes out of `ainvoke` with `During task with name '<node>'` added to `__notes__`, but the traceback is 8 frames longer, 6 of them inside the library.
- **A live latency comparison on a free tier is noise**: the same query took 2.9 s once and 34 s the next time while the provider returned 503s. Measure a framework's own overhead with an instant fake model, and use the live run to check that the requests are identical.
- **A background run must outlive the shell call**: a script started with a trailing `&` inside a polling command was killed when the call ended; start long runs with the tool's background option.

