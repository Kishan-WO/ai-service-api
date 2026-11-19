# ruff: noqa: E501  (the report lines are wide)
"""Day 8 task 4: summarise 10 documents in parallel, then combine, with one deliberate failure.

The ten documents are ten sections of the institute handbook (`chat_system` v1). Three runs:
  A  sequential        concurrency 1, no failure      (the baseline: how long ten calls take in a row)
  B  parallel          concurrency 4, no failure      (the same work, with the limit)
  C  parallel, d7 fails concurrency 4, document d7's call always fails (the failure policy)

    uv run python scripts/run_summarise_demo.py
"""

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from ai_service.core.config import get_settings
from ai_service.services.llm import SettingsLLMRegistry
from ai_service.services.llm_accounting import LLMCallRecord
from ai_service.services.llm_types import (
    LLMClient,
    LLMError,
    LLMRequest,
    LLMResponse,
    OverloadedError,
)
from ai_service.services.prompt_registry import get_prompt
from ai_service.services.summarise_service import Document, summarise_documents

PAUSE_SECONDS = 62  # keeps three runs of 11 calls under the free tier's 15 calls per minute


class ListRecorder:
    def __init__(self) -> None:
        self.records: list[LLMCallRecord] = []

    async def record(self, call: LLMCallRecord) -> None:
        self.records.append(call)


class FailingOn:
    """Wraps a client; the call whose prompt contains `marker` always fails (no model call made)."""

    def __init__(self, inner: LLMClient, marker: str) -> None:
        self._inner = inner
        self._marker = marker
        self.backend = inner.backend
        self.model = inner.model

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if self._marker in request.messages[-1].content:
            raise OverloadedError("503: the model is overloaded (injected for this test)")
        return await self._inner.generate(request)

    async def generate_structured(self, *a: Any, **k: Any) -> LLMResponse:
        raise NotImplementedError

    def stream(self, *a: Any, **k: Any) -> Any:
        raise NotImplementedError


def handbook_documents(count: int) -> list[Document]:
    """The first `count` sections of the handbook that are long enough to be worth summarising."""
    text = get_prompt("chat_system", "v1").render()
    sections = re.split(r"\n(?=# )", text)
    sections = [s.strip() for s in sections if len(s.strip()) > 400]
    return [Document(f"d{i}", s) for i, s in enumerate(sections[:count], start=1)]


async def run(
    name: str, docs: list[Document], client: LLMClient, rec: ListRecorder, **opts: Any
) -> dict[str, Any]:
    start = len(rec.records)
    t0 = time.perf_counter()
    result = await summarise_documents(docs, client, **opts)
    wall = time.perf_counter() - t0
    records = rec.records[start:]
    row = {
        "run": name,
        "concurrency": opts["concurrency"],
        "wall_seconds": round(wall, 2),
        "map_seconds": result.map_seconds,
        "combine_seconds": result.combine_seconds,
        "calls_made": result.calls,
        "calls_reaching_the_model": len(records),
        "peak_in_flight": result.peak_in_flight,
        "coverage": result.coverage,
        "failed": [f.__dict__ for f in result.failed],
        "input_tokens": result.usage.prompt_tokens,
        "output_tokens": result.usage.output_tokens,
        "cost_usd": round(sum(float(r.cost_usd or 0) for r in records), 6),
        "overview": result.overview,
        "summaries": result.summaries,
    }
    print(
        f"{name:<22} wall {row['wall_seconds']:>6} s | map {row['map_seconds']:>6} s | "
        f"calls {row['calls_made']:>2} | peak in flight {row['peak_in_flight']} | {row['coverage']}",
        flush=True,
    )
    return row


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("scripts/results/summarise_demo.json"))
    parser.add_argument("--pause", type=int, default=PAUSE_SECONDS)
    args = parser.parse_args()

    rec = ListRecorder()
    registry = SettingsLLMRegistry(
        get_settings().model_copy(update={"LLM_REQUESTS_PER_MINUTE": 0, "LLM_MAX_CONCURRENCY": 20}),
        rec,
    )
    client = registry.get("hosted")
    docs = handbook_documents(10)
    print(
        f"\nmodel: {client.model} | {len(docs)} documents, {sum(len(d.text) for d in docs)} characters\n"
    )

    rows = [await run("A sequential", docs, client, rec, concurrency=1)]
    await asyncio.sleep(args.pause)
    rows.append(await run("B parallel (limit 4)", docs, client, rec, concurrency=4))
    await asyncio.sleep(args.pause)
    try:
        rows.append(
            await run(
                "C parallel, d7 fails",
                docs,
                FailingOn(client, docs[6].text[:80]),
                rec,
                concurrency=4,
            )
        )
    except LLMError as exc:  # pragma: no cover
        print(f"run C stopped: {exc.kind}")
    await registry.aclose()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"documents": [d.id for d in docs], "rows": rows}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nsaved {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
