# ruff: noqa: E501  (the report lines are wide)
"""Day 8 task 5: the plain-code router against the LangGraph router.

Measures, on my own code:
  1 lines of code of the flow (plain `route()` against the graph module)
  2 hidden prompts and extra calls: every request that leaves the process, compared field by field
  3 the cost of the framework itself: time per request with a model that answers instantly
  4 latency with the real small model, the same queries through both flows, alternating
  5 debuggability: how deep the traceback is when a call fails, and how much of it is library code
  6 what the framework adds to the install: new packages, size on disk, import time

    uv run python scripts/run_router_framework_compare.py
"""

import argparse
import ast
import asyncio
import importlib.metadata as md
import json
import statistics
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from ai_service.core.config import get_settings
from ai_service.core.exceptions import LLMUnavailableError
from ai_service.services import router_graph, router_service
from ai_service.services.llm import SettingsLLMRegistry
from ai_service.services.llm_accounting import LLMCallRecord
from ai_service.services.llm_types import (
    LLMClient,
    LLMError,
    LLMRequest,
    LLMResponse,
    Usage,
)
from ai_service.services.router_graph import route_with_graph
from ai_service.services.router_service import route

ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT / "data" / "router_cost_sample.json"
NEW_PACKAGES = [
    "langgraph", "langgraph-checkpoint", "langgraph-prebuilt", "langgraph-sdk", "langchain-core",
    "langchain-protocol", "langsmith", "jsonpatch", "jsonpointer", "orjson", "ormsgpack",
    "requests", "requests-toolbelt", "tenacity", "urllib3", "uuid-utils", "xxhash",
    "zstandard", "charset-normalizer", "distro",
]  # fmt: skip


# ---------- 1 lines of code
def code_lines(source: str) -> int:
    """Non-blank lines that are not comments and not docstrings."""
    tree = ast.parse(source)
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                doc_lines.update(range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1))
    count = 0
    for number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and number not in doc_lines:
            count += 1
    return count


def lines_of(path: Path, names: list[str]) -> int:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = [n for n in tree.body if getattr(n, "name", None) in names]
    assert len(wanted) == len(names), (names, [getattr(n, "name", n) for n in tree.body])
    return sum(code_lines(ast.get_source_segment(source, n) or "") for n in wanted)


# ---------- a model that answers instantly (for the framework's own cost) and one that records
class Instant:
    backend, model = "fake", "fake-model"

    def __init__(self, label: str = "fees", fail: bool = False) -> None:
        self.label, self.fail = label, fail
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.fail and request.context.feature != "router_classify":
            raise LLMError("injected failure")
        text = self.label if request.context.feature == "router_classify" else "answer"
        return LLMResponse(text, "stop", Usage(10, 5), self.model, self.backend)

    async def generate_structured(self, *a: Any, **k: Any) -> LLMResponse:
        raise NotImplementedError

    def stream(self, *a: Any, **k: Any) -> Any:
        raise NotImplementedError


class Recording:
    """Wraps a client and keeps every request that goes through it."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.backend, self.model = inner.backend, inner.model
        self.requests: list[LLMRequest] = []
        self.latencies: list[float] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return await self.inner.generate(request)

    async def generate_structured(self, *a: Any, **k: Any) -> LLMResponse:
        raise NotImplementedError

    def stream(self, *a: Any, **k: Any) -> Any:
        raise NotImplementedError


def fingerprint(client: Recording) -> list[Any]:
    return [
        (
            [(m.role, m.content) for m in r.messages],
            r.max_tokens,
            r.context.feature,
            r.context.prompt_name,
            r.context.prompt_version,
        )
        for r in client.requests
    ]


class ListRecorder:
    def __init__(self) -> None:
        self.records: list[LLMCallRecord] = []

    async def record(self, call: LLMCallRecord) -> None:
        self.records.append(call)


async def per_request_us(flow: Any, message: str, label: str, runs: int) -> float:
    small, large = Instant(label), Instant()
    for _ in range(50):  # warm up
        await flow(message, small_client=small, large_client=large)
    started = time.perf_counter()
    for _ in range(runs):
        await flow(message, small_client=small, large_client=large)
    return (time.perf_counter() - started) / runs * 1e6


def traceback_shape(exc: BaseException) -> dict[str, Any]:
    frames = traceback.extract_tb(exc.__traceback__)
    lib = [f for f in frames if "site-packages" in f.filename]
    return {
        "frames": len(frames),
        "frames_in_libraries": len(lib),
        "libraries": sorted(
            {Path(f.filename).parts[Path(f.filename).parts.index("site-packages") + 1] for f in lib}
        ),
        "exception": f"{type(exc).__module__}.{type(exc).__name__}",
        "notes": list(getattr(exc, "__notes__", [])),
    }


async def failure_shape(flow: Any) -> dict[str, Any]:
    try:
        await flow(
            "How much is the course?",
            small_client=Instant("fees", fail=True),
            large_client=Instant(),
        )
    except LLMUnavailableError as exc:
        return traceback_shape(exc)
    raise AssertionError("the flow should have failed")


def import_seconds(module: str) -> float:
    """Wall time of a cold `python -c "import ..."` in a new process (best of 3)."""
    best = 1e9
    for _ in range(3):
        started = time.perf_counter()
        subprocess.run([sys.executable, "-c", f"import {module}"], check=True)
        best = min(best, time.perf_counter() - started)
    return round(best, 2)


def installed_mb(names: list[str]) -> float:
    total = 0
    for name in names:
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        for f in dist.files or []:
            path = Path(str(dist.locate_file(f)))
            if path.is_file():
                total += path.stat().st_size
    return round(total / 1e6, 1)


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out", type=Path, default=Path("scripts/results/router_framework_compare.json")
    )
    parser.add_argument("--runs", type=int, default=3000)
    parser.add_argument("--skip-live", action="store_true")
    args = parser.parse_args()
    out: dict[str, Any] = {}

    # 1 ------------------------------------------------------------------
    plain_loc = lines_of(Path(router_service.__file__), ["route"])
    graph_names = [
        "RouterState",
        "RouterDeps",
        "_ctx",
        "rules",
        "classify",
        "_answer",
        "answer_known",
        "answer_large",
        "after_rules",
        "after_classify",
        "build_router_graph",
        "result_from_state",
        "route_with_graph",
    ]
    graph_loc = lines_of(Path(router_graph.__file__), graph_names)
    out["lines_of_code"] = {
        "plain_route": plain_loc,
        "graph_module": graph_loc,
        "graph_nodes_only": lines_of(
            Path(router_graph.__file__),
            [
                "rules",
                "classify",
                "_answer",
                "answer_known",
                "answer_large",
                "after_rules",
                "after_classify",
                "build_router_graph",
            ],
        ),
    }
    print("1 lines of code (no blanks, comments or docstrings; shared helpers not counted):")
    print(f"   plain route(): {plain_loc} | graph module: {graph_loc}  ({out['lines_of_code']})\n")

    # 3 ------------------------------------------------------------------
    rows = {}
    for name, message, label in [
        ("a rule answers (no classify call)", "Hi", "fees"),
        ("classify + known answer", "How much is the course?", "fees"),
        ("classify + large answer", "Everything is wrong", "unclear"),
    ]:
        plain_us = await per_request_us(route, message, label, args.runs)
        graph_us = await per_request_us(route_with_graph, message, label, args.runs)
        rows[name] = {
            "plain_us": round(plain_us, 1),
            "graph_us": round(graph_us, 1),
            "extra_us": round(graph_us - plain_us, 1),
        }
        print(
            f"3 {name:<36} plain {plain_us:>7.1f} us | graph {graph_us:>7.1f} us | extra {graph_us - plain_us:>7.1f} us"
        )
    out["framework_overhead_per_request"] = rows
    out["graph_compile_ms"] = round(min(_time_compile() for _ in range(5)) * 1000, 2)
    print(
        f"   compiling the graph once: {out['graph_compile_ms']} ms (done at import, not per request)\n"
    )

    # 5 ------------------------------------------------------------------
    out["failure_traceback"] = {
        "plain": await failure_shape(route),
        "graph": await failure_shape(route_with_graph),
    }
    print("5 when the answer call fails:")
    for k, v in out["failure_traceback"].items():
        print(f"   {k:<6} {v}")
    print()

    # 6 ------------------------------------------------------------------
    out["install"] = {
        "new_packages": len(NEW_PACKAGES),
        "size_mb_on_disk": installed_mb(NEW_PACKAGES),
        "import_seconds_plain_router": import_seconds("ai_service.services.router_service"),
        "import_seconds_graph_router": import_seconds("ai_service.services.router_graph"),
    }
    print(f"6 install: {out['install']}\n")

    # 2 and 4 ------------------------------------------------------------
    if not args.skip_live:
        sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
        rec = ListRecorder()
        registry = SettingsLLMRegistry(
            get_settings().model_copy(update={"LLM_REQUESTS_PER_MINUTE": 12}), rec
        )
        base = registry.get("hosted")
        print(
            f"2/4 live: {len(sample)} queries through both flows, model {base.model} (also as the 'large' model: this compares the flows, not the models)\n"
        )
        live: list[dict[str, Any]] = []
        for q in sample:
            row: dict[str, Any] = {"id": q["id"], "message": q["message"]}
            order = [("plain", route), ("graph", route_with_graph)]
            if (
                q["id"] % 2 == 0
            ):  # alternate who goes first, so neither always meets a cold connection
                order.reverse()
            for name, flow in order:
                small, large = Recording(base), Recording(base)
                try:
                    result = await flow(
                        q["message"],
                        small_client=small,
                        large_client=large,
                        max_tokens=512,
                        large_max_tokens=512,
                    )
                except LLMUnavailableError:  # the provider was overloaded: keep going
                    row[name] = {
                        "failed": True,
                        "intent": None,
                        "requests": fingerprint(small) + fingerprint(large),
                        "calls": len(small.requests) + len(large.requests),
                        "total_ms": None,
                    }
                    continue
                row[name] = {
                    "intent": result.intent,
                    "rule_matched": result.rule_matched,
                    "total_ms": result.total_latency_ms,
                    "calls": len(small.requests) + len(large.requests),
                    "requests": fingerprint(small) + fingerprint(large),
                    "tokens": (result.total_usage.prompt_tokens, result.total_usage.output_tokens)
                    if result.total_usage
                    else None,
                }
            if row["plain"].get("failed") or row["graph"].get("failed"):
                row["provider_failed"] = True
                live.append(row)
                print(
                    f"{q['id']:>2} skipped: the provider failed in at least one flow (plain failed={bool(row['plain'].get('failed'))}, graph failed={bool(row['graph'].get('failed'))})",
                    flush=True,
                )
                continue
            row["same_intent"] = row["plain"]["intent"] == row["graph"]["intent"]
            row["same_requests"] = row["plain"]["requests"] == row["graph"]["requests"]
            row["same_calls"] = row["plain"]["calls"] == row["graph"]["calls"]
            live.append(row)
            print(
                f"{q['id']:>2} intent plain {row['plain']['intent']:<10} graph {row['graph']['intent']:<10} | calls {row['plain']['calls']}/{row['graph']['calls']} | same requests {row['same_requests']} | ms plain {row['plain']['total_ms']:>7} graph {row['graph']['total_ms']:>7}",
                flush=True,
            )
        ok = [r for r in live if not r.get("provider_failed")]
        live = ok + [r for r in live if r.get("provider_failed")]
        plain_ms = [r["plain"]["total_ms"] for r in ok]
        graph_ms = [r["graph"]["total_ms"] for r in ok]
        out["live"] = {
            "queries": len(ok),
            "skipped_provider_failed": len(live) - len(ok),
            "same_intent": sum(r["same_intent"] for r in ok),
            "same_requests": sum(r["same_requests"] for r in ok),
            "same_call_count": sum(r["same_calls"] for r in ok),
            "median_ms": {
                "plain": statistics.median(plain_ms),
                "graph": statistics.median(graph_ms),
            },
            "mean_ms": {
                "plain": round(statistics.mean(plain_ms), 1),
                "graph": round(statistics.mean(graph_ms), 1),
            },
            "rows": live,
        }
        print(
            f"\n   {out['live']['same_intent']}/{len(ok)} same intent | {out['live']['same_requests']}/{len(ok)} identical requests | median ms {out['live']['median_ms']}"
        )
        await registry.aclose()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(f"\nsaved {args.out}")


def _time_compile() -> float:
    started = time.perf_counter()
    router_graph.build_router_graph()
    return time.perf_counter() - started


if __name__ == "__main__":
    asyncio.run(main())
