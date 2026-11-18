"""Day 7 task 5: measure the classify_query prompt versions on a labelled test set.

For every version (v1 zero-shot, v2 structure and rules, v3 few-shot, v4 chain-of-thought) it
records accuracy, tokens, cost, latency and how many replies were in the asked format, and it
lists every wrong answer and every case on which the versions disagree.

Tokens, cost and latency come from the same accounting layer the service uses (AccountingClient),
so latency is the provider call itself, not time spent waiting in the rate limiter.

Run (the hosted free tier allows 15 calls per minute, so a limit of 12 is on by default):
    uv run python scripts/run_classify_eval.py
    uv run python scripts/run_classify_eval.py --cases scripts/data/classify_cases_easy.json \
        --out scripts/results/classify_eval_easy.json
"""

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_service.core.config import get_settings
from ai_service.services.llm import Backend, SettingsLLMRegistry
from ai_service.services.llm_accounting import LLMCallRecord
from ai_service.services.llm_types import CallContext, ChatMessage, LLMClient, LLMRequest
from ai_service.services.prompt_registry import get_prompt

HERE = Path(__file__).resolve().parent
DEFAULT_CASES = HERE / "data" / "classify_cases.json"
DEFAULT_OUT = HERE / "results" / "classify_eval.json"
PROMPT_NAME = "classify_query"

CATEGORIES = {"admission", "fees", "schedule", "academic", "complaint", "other"}


def parse_category(text: str) -> tuple[str, bool]:
    """(label, format_ok). format_ok is False when the label had to be dug out of free text.

    Accepted as well formed: a bare label ("fees"), or a "CATEGORY: fees" line (version v4).
    Anything else is read leniently (the first label word found) and marked, so I can see how
    well each version obeys the output format. No label at all gives "unknown" (counted wrong).
    """
    bare = text.strip().strip("*`'\". ").lower()
    if bare in CATEGORIES:
        return bare, True
    match = re.search(r"CATEGORY:\s*\**\s*([a-zA-Z_]+)", text, re.IGNORECASE)
    if match and match.group(1).lower() in CATEGORIES:
        return match.group(1).lower(), True
    for word in re.findall(r"[a-zA-Z_]+", text.lower()):
        if word in CATEGORIES:
            return word, False
    return "unknown", False


class ListRecorder:
    """Keeps every call record in memory (the registry's accounting layer fills it)."""

    def __init__(self) -> None:
        self.records: list[LLMCallRecord] = []

    async def record(self, call: LLMCallRecord) -> None:
        self.records.append(call)


@dataclass
class EvalResult:
    case_id: int
    expected: str
    predicted: str
    correct: bool
    format_ok: bool
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    retries: int
    raw: str


async def evaluate_version(
    client: LLMClient, recorder: ListRecorder, version: str, cases: list[dict[str, Any]]
) -> list[EvalResult]:
    prompt = get_prompt(PROMPT_NAME, version)
    context = CallContext(
        feature="classify_eval", prompt_name=prompt.name, prompt_version=prompt.version
    )
    results: list[EvalResult] = []
    for case in cases:
        request = LLMRequest(
            [ChatMessage("user", prompt.render(message=case["message"]))],
            max_tokens=250,
            context=context,
        )
        before = len(recorder.records)
        try:
            response = await client.generate(request)
            raw = response.text.strip()
        except Exception as exc:  # a failed call is a wrong answer, not a crashed run
            raw = f"ERROR: {type(exc).__name__}: {exc}"
        calls = recorder.records[before:]
        last = calls[-1] if calls else None
        usage = last.usage if last and last.status == "ok" else None
        predicted, format_ok = (
            parse_category(raw) if not raw.startswith("ERROR:") else ("error", False)
        )
        results.append(
            EvalResult(
                case_id=case["id"],
                expected=case["category"],
                predicted=predicted,
                correct=predicted == case["category"],
                format_ok=format_ok,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                cost_usd=float(last.cost_usd) if last and last.cost_usd is not None else 0.0,
                latency_ms=last.latency_ms if last else 0.0,
                retries=max(len(calls) - 1, 0),
                raw=raw,
            )
        )
    return results


def print_table(rows: list[list[str]], headers: list[str]) -> None:
    widths = [max(len(r[i]) for r in [headers, *rows]) for i in range(len(headers))]
    print(" | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(" | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="Evaluate classify_query prompt versions.")
    parser.add_argument("--versions", nargs="+", default=["v1", "v2", "v3", "v4"])
    parser.add_argument("--backend", choices=["hosted", "local", "anthropic"], default="hosted")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--rpm", type=int, default=12, help="calls per minute for hosted (0 = off)")
    args = parser.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in cases}
    settings = get_settings().model_copy(update={"LLM_REQUESTS_PER_MINUTE": args.rpm})
    recorder = ListRecorder()
    registry = SettingsLLMRegistry(settings, recorder)
    backend: Backend = args.backend
    client = registry.get(backend)

    print(
        f"\nclassify_query on {backend} ({client.model}), {len(cases)} cases from {args.cases.name}"
    )
    print(f"rate limit: {args.rpm} calls per minute\n")

    stats: dict[str, dict[str, Any]] = {}
    all_results: dict[str, list[EvalResult]] = {}
    started = time.perf_counter()
    for version in args.versions:
        print(f"{version} ...", end=" ", flush=True)
        results = await evaluate_version(client, recorder, version, cases)
        all_results[version] = results
        correct = sum(r.correct for r in results)
        stats[version] = {
            "correct": correct,
            "total": len(results),
            "accuracy": 100 * correct / len(results),
            "format_ok": sum(r.format_ok for r in results),
            "in_tokens": statistics.mean(r.input_tokens for r in results),
            "out_tokens": statistics.mean(r.output_tokens for r in results),
            "cost": statistics.mean(r.cost_usd for r in results),
            "lat_med": statistics.median(r.latency_ms for r in results) / 1000,
            "lat_p95": sorted(r.latency_ms for r in results)[int(0.95 * len(results))] / 1000,
            "retries": sum(r.retries for r in results),
        }
        print(f"{correct}/{len(results)} correct")
    await registry.aclose()

    print("\n" + "=" * 100)
    headers = [
        "Ver",
        "Correct",
        "Format ok",
        "In tok",
        "Out tok",
        "Cost/call",
        "Cost/1K",
        "Median",
        "p95",
        "Retries",
    ]
    rows = [
        [
            v,
            f"{s['correct']}/{s['total']} ({s['accuracy']:.1f}%)",
            f"{s['format_ok']}/{s['total']}",
            f"{s['in_tokens']:.0f}",
            f"{s['out_tokens']:.0f}",
            f"${s['cost']:.6f}",
            f"${s['cost'] * 1000:.4f}",
            f"{s['lat_med']:.2f}s",
            f"{s['lat_p95']:.2f}s",
            str(s["retries"]),
        ]
        for v, s in stats.items()
    ]
    print_table(rows, headers)
    print("=" * 100)

    print("\nWRONG ANSWERS")
    for v, results in all_results.items():
        for r in (r for r in results if not r.correct):
            msg = by_id[r.case_id]["message"][:70]
            print(
                f"  {v} case {r.case_id:>2}: expected {r.expected:<9} got {r.predicted:<9} | {msg}"
            )
    print("\nCASES WHERE THE VERSIONS DISAGREE")
    disagree = [
        cid
        for cid in by_id
        if len({next(r for r in all_results[v] if r.case_id == cid).predicted for v in all_results})
        > 1
    ]
    for cid in disagree:
        votes = {
            v: next(r for r in all_results[v] if r.case_id == cid).predicted for v in all_results
        }
        print(f"  case {cid:>2} (expected {by_id[cid]['category']}): {votes}")
    if not disagree:
        print("  none: every version gave the same answer on every case")

    best = max(s["accuracy"] for s in stats.values())
    one_case = 100 / len(cases)
    strict = [v for v, s in stats.items() if s["accuracy"] >= best - 2.0 - 1e-9]
    lenient = [v for v, s in stats.items() if s["accuracy"] >= best - one_case - 1e-9]
    cheapest_strict = min(strict, key=lambda v: stats[v]["cost"])
    cheapest_lenient = min(lenient, key=lambda v: stats[v]["cost"])
    print("\nDECISION (rule from the plan: the cheapest version within 2 points of the best)")
    print(f"  best accuracy: {best:.1f}%   |   one case = {one_case:.1f} points")
    print(f"  within 2 points: {', '.join(strict)}  ->  cheapest: {cheapest_strict}")
    print(f"  within 1 case:   {', '.join(lenient)}  ->  cheapest: {cheapest_lenient}")
    elapsed = time.perf_counter() - started
    print(f"  provider calls: {len(recorder.records)}  |  wall time: {elapsed:.0f}s")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "model": client.model,
                "cases_file": args.cases.name,
                "stats": stats,
                "versions": {
                    v: [r.__dict__ for r in results] for v, results in all_results.items()
                },
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nsaved {args.out}\n")


if __name__ == "__main__":
    asyncio.run(main())
