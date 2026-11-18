# Q47. What are the issues with the large model (`gemini-3-flash-preview`)?

**What I asked:** "what is issue regarding large model ?"

## The short answer
Four issues. Three are fixed in code, one is a limit I have to live with.

1. **`POST /route` could not select it.** The route took backend names (`hosted` is Flash-Lite, the small model), so escalated queries went to the small model through the API. **Fixed:** a second backend `hosted_large` with its own settings `LLM_LARGE_MODEL` and `LLM_LARGE_REQUESTS_PER_MINUTE`. `large_backend` in the request is optional; the route uses `hosted_large` when `LLM_LARGE_MODEL` is set, otherwise `hosted`. To use it: `LLM_LARGE_MODEL=gemini-3-flash-preview` in `.env`.
2. **Thinking tokens use up the answer cap.** It spent about 450 of its 544 average output tokens on thinking, and the cap counts them. In case 12 it used 996 of 1,000 tokens thinking and the answer stopped mid-sentence. **Fixed:** `route()` has `large_max_tokens=2000`, with a test. The measurement run itself still used 1000.
3. **Its free quota is very small.** 20 requests a day, so the cost measurement had only 14 queries and one run. The 53.9% saving is a pilot result, not proof.
4. **Thinking tokens are hidden in the usage numbers.** The API reported `completion_tokens=1` while the real output was much larger, so the cost was under-counted. **Fixed:** `usage_from_openai` takes the larger of `completion_tokens` and `total_tokens - prompt_tokens`.

Other models I tried as the large model and rejected: `gemma-4-31b-it` (a 503, 24 s, its reasoning came back as text with 0 completion tokens) and the Pro models (no free quota).
