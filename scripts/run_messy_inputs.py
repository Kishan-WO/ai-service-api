"""Send the 50 messy inputs through POST /extract and report what happened to each.

Run the service first (with a real key), then:

    uv run python scripts/run_messy_inputs.py --base-url http://localhost:8010

Outcomes:
  valid              HTTP 200 and valid on the first try
  repaired           HTTP 200 after the model was shown its mistake (attempts 2 or 3)
  correctly_refused  the input should be refused and was (empty, too long: 422 before any model)
  failed             a handled error where an answer was expected (422 EXTRACTION_FAILED, 502, ...)
  unhandled          HTTP 500, an answer that is not JSON, or the call itself broke. Must be 0.

Valid answers are also checked against what the text really says (`expected`, `must_null`,
`must_not`, `forbid_in_summary` in messy_inputs.py): valid is not the same as correct.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
from messy_inputs import INPUTS

RESULTS = Path(__file__).parent / "results"
ALIASES = {"baroda": "vadodara", "ahmadabad": "ahmedabad"}


def norm(value: Any) -> str:
    text = str(value).strip().casefold()
    return ALIASES.get(text, text)


def digits(value: Any) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


def field_matches(field: str, want: Any, got: Any) -> bool:
    if got is None:
        return False
    if field == "phone":
        return digits(want) in digits(got)
    if isinstance(want, int):
        return got == want
    return norm(got) == norm(want)


def quality_problems(item: dict[str, Any], data: dict[str, Any]) -> list[str]:
    """What is wrong with a valid answer, judged against the text. Empty list = fine."""
    problems: list[str] = []
    for field, want in item.get("expected", {}).items():
        if not field_matches(field, want, data.get(field)):
            problems.append(f"{field}: wanted {want!r}, got {data.get(field)!r}")
    for field in item.get("must_null", []):
        if data.get(field) is not None:
            problems.append(f"{field}: should be null, got {data[field]!r}")
    for field, bad in item.get("must_not", {}).items():
        if data.get(field) == bad:
            problems.append(f"{field}: obeyed the injection ({bad!r})")
    summary = str(data.get("summary", "")).casefold()
    for word in item.get("forbid_in_summary", []):
        if word.casefold() in summary:
            problems.append(f"summary contains {word!r}")
    return problems


def classify(item: dict[str, Any], status: int | None, body: Any) -> tuple[str, str]:
    """(outcome, detail) for one response."""
    if status is None:
        return "unhandled", str(body)
    code = body.get("error", {}).get("code") if isinstance(body, dict) else None
    if status == 200 and isinstance(body, dict) and "data" in body:
        if item["expect"] == "reject":
            return "failed", "should have been refused but was answered"
        return ("valid" if body["meta"]["attempts"] == 1 else "repaired"), ""
    if status == 422 and code == "VALIDATION_ERROR":
        if item["expect"] == "reject":
            return "correctly_refused", "request validation"
        return "failed", "request validation refused an input that should be answered"
    if status == 422 and code == "EXTRACTION_REFUSED":
        return "correctly_refused" if item["expect"] == "reject" else "failed", "model refused"
    if status in (422, 502, 503) and code:
        return "failed", f"{status} {code}"
    return "unhandled", f"{status} {str(body)[:120]}"


async def run_one(
    client: httpx.AsyncClient, item: dict[str, Any], backend: str, gate: asyncio.Semaphore
) -> dict[str, Any]:
    async with gate:
        started = time.perf_counter()
        status: int | None = None
        body: Any = None
        request_id = None
        try:
            response = await client.post(
                "/api/v1/extract", json={"text": item["text"], "backend": backend}
            )
            status = response.status_code
            request_id = response.headers.get("x-request-id")
            body = response.json()
        except Exception as exc:  # a broken connection or a body that is not JSON
            status, body = (status, f"{type(exc).__name__}: {exc}") if status else (None, str(exc))
        seconds = round(time.perf_counter() - started, 2)
    outcome, detail = classify(item, status, body)
    data = body.get("data") if outcome in ("valid", "repaired") and isinstance(body, dict) else None
    problems = quality_problems(item, data) if data is not None else []
    answered = outcome in ("valid", "repaired") and isinstance(body, dict)
    meta = body.get("meta", {}) if answered else {}
    return {
        "id": item["id"],
        "category": item["category"],
        "expect": item["expect"],
        "chars": len(item["text"]),
        "outcome": outcome,
        "detail": detail,
        "status": status,
        "seconds": seconds,
        "attempts": meta.get("attempts"),
        "fallback_used": meta.get("fallback_used"),
        "problems": problems,
        "request_id": request_id,
        "data": data,
    }


async def database_totals(request_ids: list[str]) -> dict[str, Any] | None:
    url = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    if not url.startswith("postgresql://"):
        return None
    import asyncpg

    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            "select status, count(*) as calls, coalesce(sum(cost_usd), 0) as cost,"
            " coalesce(sum(input_tokens), 0) as input, coalesce(sum(output_tokens), 0) as output,"
            " coalesce(sum(cache_read_tokens), 0) as cached"
            " from llm_calls where request_id = any($1) group by status",
            request_ids,
        )
    finally:
        await conn.close()
    return {
        "by_status": {r["status"]: r["calls"] for r in rows},
        "provider_calls": sum(r["calls"] for r in rows),
        "cost_usd": float(sum(r["cost"] for r in rows)),
        "input_tokens": sum(r["input"] for r in rows),
        "output_tokens": sum(r["output"] for r in rows),
        "cache_read_tokens": sum(r["cached"] for r in rows),
    }


async def main() -> None:
    # the Windows console is cp1252: an emoji in a note must not crash the report
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8010")
    parser.add_argument("--backend", default="hosted")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--only", type=int, nargs="*", help="run only these ids")
    parser.add_argument("--out", default=str(RESULTS / "messy_inputs_report.json"))
    args = parser.parse_args()

    items = [i for i in INPUTS if not args.only or i["id"] in args.only]
    async with httpx.AsyncClient(base_url=args.base_url, timeout=300) as client:
        email = f"messy-{uuid.uuid4().hex[:8]}@example.com"
        registered = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "correct-horse-battery", "tenant_name": "Messy run"},
        )
        registered.raise_for_status()
        client.headers["Authorization"] = f"Bearer {registered.json()['access_token']}"

        started = time.perf_counter()
        gate = asyncio.Semaphore(args.concurrency)
        results = await asyncio.gather(*[run_one(client, i, args.backend, gate) for i in items])
        wall = round(time.perf_counter() - started, 1)

    outcomes = Counter(r["outcome"] for r in results)
    answered = [r for r in results if r["outcome"] in ("valid", "repaired")]
    checked_bad = [r for r in answered if r["problems"]]
    seconds = sorted(r["seconds"] for r in answered)
    request_ids = [r["request_id"] for r in results if r["request_id"]]
    totals = await database_totals(request_ids)

    summary = {
        "backend": args.backend,
        "inputs": len(results),
        "wall_seconds": wall,
        "outcomes": dict(outcomes),
        "attempts": dict(Counter(r["attempts"] for r in answered)),
        "answers_with_a_wrong_field": len(checked_bad),
        "median_seconds": statistics.median(seconds) if seconds else None,
        "slowest_seconds": seconds[-1] if seconds else None,
        "database": totals,
    }

    # saved first: a crash while printing must not lose a 10-minute run
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"\n{'id':>3}  {'category':<15} {'outcome':<18} {'tries':>5} {'sec':>6}  notes")
    for r in results:
        notes = r["detail"] or "; ".join(r["problems"])
        print(
            f"{r['id']:>3}  {r['category']:<15} {r['outcome']:<18} {r['attempts'] or '-':>5} "
            f"{r['seconds']:>6}  {notes}"
        )
    print("\n" + json.dumps(summary, indent=2))
    print(f"\nsaved {args.out}")
    if outcomes["unhandled"]:
        raise SystemExit(f"{outcomes['unhandled']} unhandled error(s)")


if __name__ == "__main__":
    asyncio.run(main())
