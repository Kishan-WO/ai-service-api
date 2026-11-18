# ruff: noqa: E501  (the report tables are wide print lines)
"""Day 8 task 3: the router against ALWAYS-LARGE, on cost, latency and answer quality.

For every sample query (scripts/data/router_cost_sample.json):
  always-large  the large model answers with the full handbook (the product's real chat prompt)
  router        rules, then the small model classifies and answers with the intent's handbook slice;
                an unclear query goes to the large model with the full handbook
The large model has only 20 free requests a day, so the sample is small (14) and a query the router
escalates REUSES the always-large call (same model, same prompt): the router's cost for it is the
classifier call plus that call. Quality is a rubric of facts that the handbook contains: an item
passes when any one of its alternatives appears in the answer.

    uv run python scripts/run_router_cost_eval.py
"""

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from ai_service.core.config import get_settings
from ai_service.services.llm import SettingsLLMRegistry
from ai_service.services.llm_accounting import LLMCallRecord
from ai_service.services.llm_types import (
    CallContext,
    ChatMessage,
    LLMError,
    LLMRequest,
    LLMResponse,
)
from ai_service.services.prompt_registry import get_prompt
from ai_service.services.router_service import route

SAMPLE = Path(__file__).resolve().parent / "data" / "router_cost_sample.json"
LARGE_MODEL = "gemini-3-flash-preview"
MAX_TOKENS = 1000  # the same answer cap for both flows (thinking tokens count against it)


class ListRecorder:
    def __init__(self) -> None:
        self.records: list[LLMCallRecord] = []

    async def record(self, call: LLMCallRecord) -> None:
        self.records.append(call)


class ReplayClient:
    """Hands back an answer that was already paid for (the always-large call of the same query)."""

    backend = "hosted"

    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.model = response.model

    async def generate(self, request: LLMRequest) -> LLMResponse:
        return self.response


def rubric_score(answer: str, rubric: list[list[str]]) -> float:
    text = answer.lower()
    return sum(any(alt.lower() in text for alt in item) for item in rubric) / len(rubric)


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(int(q * len(ordered)), len(ordered) - 1)]


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("scripts/results/router_cost_eval.json"))
    parser.add_argument("--large-rpm", type=int, default=4)
    args = parser.parse_args()
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))

    base = get_settings()
    small_rec, large_rec = ListRecorder(), ListRecorder()
    small_reg = SettingsLLMRegistry(
        base.model_copy(update={"LLM_REQUESTS_PER_MINUTE": 12}), small_rec
    )
    large_reg = SettingsLLMRegistry(
        base.model_copy(
            update={"LLM_MODEL": LARGE_MODEL, "LLM_REQUESTS_PER_MINUTE": args.large_rpm}
        ),
        large_rec,
    )
    small, large = small_reg.get("hosted"), large_reg.get("hosted")
    handbook = get_prompt("chat_system", "v1").render()
    print(f"\nsmall: {small.model} | large: {large.model} | {len(sample)} queries\n")

    rows: list[dict[str, Any]] = []
    for q in sample:
        # ---- always-large
        before = len(large_rec.records)
        try:
            base_resp = await large.generate(
                LLMRequest(
                    [ChatMessage("system", handbook), ChatMessage("user", q["message"])],
                    max_tokens=MAX_TOKENS,
                    context=CallContext(feature="cost_eval_large"),
                )
            )
        except LLMError as exc:
            print(f"{q['id']:>2} the always-large call failed ({exc.kind}); stopping", flush=True)
            break
        rec = large_rec.records[-1] if len(large_rec.records) > before else None
        base_cost = float(rec.cost_usd or 0) if rec else 0.0
        base_ms = rec.latency_ms if rec else 0.0

        # ---- router (an escalated query reuses the call above)
        before = len(small_rec.records)
        result = await route(
            q["message"],
            small_client=small,
            large_client=ReplayClient(base_resp),
            max_tokens=MAX_TOKENS,
        )
        mine = small_rec.records[before:]
        escalated = result.answer_model == large.model
        router_cost = sum(float(r.cost_usd or 0) for r in mine) + (base_cost if escalated else 0.0)
        router_ms = sum(r.latency_ms for r in mine) + (base_ms if escalated else 0.0)
        rows.append(
            {
                "id": q["id"],
                "from": q["from"],
                "label": q["category"],
                "intent": result.intent,
                "rule": result.rule_matched,
                "escalated": escalated,
                "large_cost": base_cost,
                "large_ms": base_ms,
                "large_score": rubric_score(base_resp.text, q["rubric"]),
                "large_tokens": (base_resp.usage.prompt_tokens, base_resp.usage.output_tokens)
                if base_resp.usage
                else None,
                "router_cost": router_cost,
                "router_ms": router_ms,
                "router_score": rubric_score(result.answer, q["rubric"]),
                "large_answer": base_resp.text,
                "router_answer": result.answer,
                "message": q["message"],
            }
        )
        r = rows[-1]
        print(
            f"{q['id']:>2} {q['category']:<9} -> {result.intent:<9} {'ESC' if escalated else '   '} "
            f"cost large ${base_cost:.6f} router ${router_cost:.6f} | latency {base_ms / 1000:5.1f}s vs {router_ms / 1000:5.1f}s "
            f"| rubric {r['large_score']:.2f} vs {r['router_score']:.2f}",
            flush=True,
        )
    await small_reg.aclose()
    await large_reg.aclose()
    if not rows:
        raise SystemExit("nothing was measured")

    n = len(rows)
    lc, rc = [r["large_cost"] for r in rows], [r["router_cost"] for r in rows]
    lm, rm = [r["large_ms"] / 1000 for r in rows], [r["router_ms"] / 1000 for r in rows]
    summary = {
        "queries": n,
        "avg_cost_always_large": statistics.mean(lc),
        "avg_cost_router": statistics.mean(rc),
        "cost_saving_percent": round(100 * (1 - statistics.mean(rc) / statistics.mean(lc)), 1),
        "known_intents_only_saving_percent": None,
        "median_latency_always_large_s": round(statistics.median(lm), 2),
        "median_latency_router_s": round(statistics.median(rm), 2),
        "p95_latency_always_large_s": round(pct(lm, 0.95), 2),
        "p95_latency_router_s": round(pct(rm, 0.95), 2),
        "rubric_always_large": round(statistics.mean(r["large_score"] for r in rows), 3),
        "rubric_router": round(statistics.mean(r["router_score"] for r in rows), 3),
        "escalated": sum(r["escalated"] for r in rows),
        "large_calls_used": len(large_rec.records),
    }
    known = [r for r in rows if not r["escalated"]]
    if known:
        summary["known_intents_only_saving_percent"] = round(
            100
            * (
                1
                - statistics.mean(r["router_cost"] for r in known)
                / statistics.mean(r["large_cost"] for r in known)
            ),
            1,
        )
    print("\n" + "=" * 100)
    for k, v in summary.items():
        print(f"{k:<38} {v}")
    print("=" * 100)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {"small": small.model, "large": large.model, "summary": summary, "rows": rows},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"saved {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
