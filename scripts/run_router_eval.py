# ruff: noqa: E501  (the report tables are wide print lines)
"""Day 8 task 2: measure the ROUTER's first stage (rules, then the small model) on labelled queries.

It runs exactly what router_service.route() runs before it answers: the rule fast path, then
classify_query v5 on the small model with the router's token cap and parser. The three query files
are the 60 labelled cases of Day 7 plus the 30 new router queries (which include requests that
should be escalated to the large model, labelled "unclear").

What it reports:
  accuracy                the final intent equals the label
  escalated (correct)     labelled unclear and sent up: the large model sees it
  false escalation        labelled with a real intent but sent up: costs money, never hurts quality
  confident but wrong     a known intent that is not the label: the one that hurts quality
  rule hits and misses    how many queries the free rules caught, and how many of those were wrong

    uv run python scripts/run_router_eval.py                       (the small backend: hosted)
    uv run python scripts/run_router_eval.py --backend local --out scripts/results/router_local.json
"""

import argparse
import asyncio
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ai_service.core.config import get_settings
from ai_service.services.llm import Backend, SettingsLLMRegistry
from ai_service.services.llm_accounting import LLMCallRecord
from ai_service.services.llm_types import CallContext, ChatMessage, LLMError, LLMRequest
from ai_service.services.prompt_registry import get_prompt
from ai_service.services.router_service import (
    _CLASSIFIER_PROMPT_NAME,
    _CLASSIFIER_PROMPT_VERSION,
    _parse_intent,
    _rule_based_intent,
)

DATA = Path(__file__).resolve().parent / "data"
FILES = ["classify_cases.json", "classify_cases_easy.json", "router_queries.json"]
LABELS = ["admission", "fees", "schedule", "academic", "complaint", "other", "unclear"]


class ListRecorder:
    def __init__(self) -> None:
        self.records: list[LLMCallRecord] = []

    async def record(self, call: LLMCallRecord) -> None:
        self.records.append(call)


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["hosted", "local", "anthropic"], default="hosted")
    parser.add_argument("--rpm", type=int, default=12)
    parser.add_argument("--out", type=Path, default=Path("scripts/results/router_accuracy.json"))
    args = parser.parse_args()

    settings = get_settings().model_copy(update={"LLM_REQUESTS_PER_MINUTE": args.rpm})
    recorder = ListRecorder()
    registry = SettingsLLMRegistry(settings, recorder)
    backend: Backend = args.backend
    client = registry.get(backend)
    prompt = get_prompt(_CLASSIFIER_PROMPT_NAME, _CLASSIFIER_PROMPT_VERSION)
    print(f"\nrouter stage 1: {prompt.name}@{prompt.version} on {backend} ({client.model})\n")

    rows: list[dict[str, Any]] = []
    for file in FILES:
        for case in json.loads((DATA / file).read_text(encoding="utf-8")):
            rule = _rule_based_intent(case["message"])
            raw, ms, tokens, cost = "", 0.0, 0, 0.0
            if rule is not None:
                predicted = rule
            else:
                started = len(recorder.records)
                try:
                    reply = await client.generate(
                        LLMRequest(
                            [ChatMessage("user", prompt.render(message=case["message"]))],
                            max_tokens=20,
                            context=CallContext(feature="router_eval"),
                        )
                    )
                    raw = reply.text.strip()
                except LLMError as exc:
                    raw = f"ERROR {exc.kind}"
                predicted = _parse_intent(raw)
                last = recorder.records[-1] if len(recorder.records) > started else None
                if last is not None:
                    ms = last.latency_ms
                    tokens = (
                        last.usage.prompt_tokens + last.usage.output_tokens if last.usage else 0
                    )
                    cost = float(last.cost_usd) if last.cost_usd is not None else 0.0
            rows.append(
                {
                    "file": file,
                    "id": case["id"],
                    "expected": case["category"],
                    "predicted": predicted,
                    "rule": rule is not None,
                    "raw": raw,
                    "ms": ms,
                    "tokens": tokens,
                    "cost": cost,
                    "message": case["message"],
                }
            )
            mark = "ok " if predicted == case["category"] else "XX "
            print(
                f"{mark}{file[:8]} {case['id']:>2} {case['category']:<9} -> {predicted:<9}"
                f"{'(rule)' if rule else '      '} {case['message'][:60]}",
                flush=True,
            )
    await registry.aclose()

    def summarise(subset: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(subset)
        right = sum(r["expected"] == r["predicted"] for r in subset)
        esc_ok = sum(r["expected"] == "unclear" and r["predicted"] == "unclear" for r in subset)
        esc_total = sum(r["expected"] == "unclear" for r in subset)
        false_esc = sum(r["expected"] != "unclear" and r["predicted"] == "unclear" for r in subset)
        confident_wrong = sum(r["predicted"] not in (r["expected"], "unclear") for r in subset)
        rules = [r for r in subset if r["rule"]]
        return {
            "n": n,
            "correct": right,
            "accuracy": round(100 * right / n, 1),
            "escalated_correctly": f"{esc_ok}/{esc_total}",
            "false_escalations": false_esc,
            "confident_but_wrong": confident_wrong,
            "rule_hits": len(rules),
            "rule_wrong": sum(r["expected"] != r["predicted"] for r in rules),
        }

    print("\n" + "=" * 96)
    summary = {"ALL 90": summarise(rows)}
    for file in FILES:
        summary[file] = summarise([r for r in rows if r["file"] == file])
    for name, s in summary.items():
        print(
            f"{name:<24} correct {s['correct']:>2}/{s['n']} ({s['accuracy']:>5}%) | escalated right {s['escalated_correctly']:<5}"
            f"| false escalations {s['false_escalations']} | confident but wrong {s['confident_but_wrong']}"
            f" | rules fired {s['rule_hits']} (wrong {s['rule_wrong']})"
        )
    modelled = [r for r in rows if not r["rule"]]
    if modelled:
        print(
            f"\nclassifier calls: {len(modelled)} | median {statistics.median(r['ms'] for r in modelled) / 1000:.2f}s "
            f"| avg tokens {statistics.mean(r['tokens'] for r in modelled):.0f} "
            f"| avg cost ${statistics.mean(r['cost'] for r in modelled):.6f} per call"
        )
    print("\nconfusion table (rows = label, columns = what the router decided):")
    cm: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        cm[r["expected"]][r["predicted"]] += 1
    print(" " * 11 + "".join(f"{x[:9]:>10}" for x in LABELS))
    for e in LABELS:
        print(f"{e:<11}" + "".join(f"{cm[e][x]:>10}" for x in LABELS))
    print("\nWRONG:")
    for r in rows:
        if r["expected"] != r["predicted"]:
            print(
                f"  {r['file'][:8]} {r['id']:>2} label {r['expected']:<9} got {r['predicted']:<9} | {r['message'][:70]}"
            )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "prompt": f"{prompt.name}@{prompt.version}",
                "model": client.model,
                "summary": summary,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nsaved {args.out}  ({len(recorder.records)} provider calls)")


if __name__ == "__main__":
    asyncio.run(main())
