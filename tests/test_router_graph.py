"""Day 8 task 5: the LangGraph router gives the same results and sends the same prompts as the
plain `route()`; and the things only the graph gives (steps, a drawing, pause and resume)."""

from dataclasses import replace
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from ai_service.core.exceptions import LLMUnavailableError
from ai_service.services.llm_types import (
    CallContext,
    LLMError,
    LLMRequest,
    LLMResponse,
    Usage,
)
from ai_service.services.router_graph import (
    ROUTER_GRAPH,
    RouterDeps,
    build_router_graph,
    route_with_graph,
)
from ai_service.services.router_service import RouterResult, route


class Script:
    """A model that answers a classification with `label` and any other call with `answer`."""

    def __init__(
        self, label: str = "fees", answer: str = "an answer", *, fail: str | None = None
    ) -> None:
        self.label, self.answer, self.fail = label, answer, fail
        self.backend, self.model = "fake", "fake-model"
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        kind = "classify" if request.context.feature == "router_classify" else "answer"
        if self.fail == kind:
            raise LLMError("boom")
        text = self.label if kind == "classify" else self.answer
        return LLMResponse(text, "stop", Usage(10, 5), self.model, self.backend)

    async def generate_structured(self, *a: Any, **k: Any) -> LLMResponse:
        raise NotImplementedError

    def stream(self, *a: Any, **k: Any) -> Any:
        raise NotImplementedError


def sent(client: Script) -> list[tuple[Any, ...]]:
    """What left the process, call by call: the prompt text and everything that shapes the call."""
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


def comparable(result: RouterResult) -> RouterResult:
    return replace(result, classify_latency_ms=0, answer_latency_ms=0, total_latency_ms=0)


CASES = [
    ("Hi", "fees", "none"),  # a rule answers, no classification
    ("I was charged twice for my course", "fees", "none"),  # a rule beats the model
    ("How much is the Python course?", "fees", "none"),  # the small model classifies
    ("When does the next batch start?", "schedule", "none"),
    ("my laptop, my fees, my teacher, everything is wrong", "unclear", "none"),  # large model
    ("something", "this is not a label", "none"),  # garbage label -> unclear
    ("How much is the course?", "fees", "classify"),  # classifier fails -> unclear
]


@pytest.mark.parametrize(("message", "label", "fail"), CASES)
async def test_the_graph_and_the_plain_flow_agree_and_send_the_same_prompts(
    message: str, label: str, fail: str
) -> None:
    plain_small, plain_large = Script(label, "small", fail=fail), Script(label, "large")
    graph_small, graph_large = Script(label, "small", fail=fail), Script(label, "large")

    plain = await route(message, small_client=plain_small, large_client=plain_large)
    graph = await route_with_graph(message, small_client=graph_small, large_client=graph_large)

    assert comparable(graph) == comparable(plain)
    assert sent(graph_small) == sent(plain_small)  # no hidden prompt, no extra call, same caps
    assert sent(graph_large) == sent(plain_large)


async def test_a_failed_answer_call_is_the_same_clean_error() -> None:
    for flow in (route, route_with_graph):
        with pytest.raises(LLMUnavailableError):
            await flow(
                "How much is the course?", small_client=Script(fail="answer"), large_client=Script()
            )


async def test_the_graph_streams_one_update_per_step() -> None:
    deps = RouterDeps(Script("fees"), Script(), CallContext(feature="t"))
    steps = [
        list(update)[0]
        async for update in ROUTER_GRAPH.astream(
            {"message": "How much is the course?"}, context=deps, stream_mode="updates"
        )
    ]
    assert steps == ["rules", "classify", "answer_known"]


async def test_the_graph_can_pause_before_the_large_model_and_resume() -> None:
    graph = build_router_graph(checkpointer=InMemorySaver(), interrupt_before=["answer_large"])
    small, large = Script("unclear"), Script(answer="from large")
    deps = RouterDeps(small, large, CallContext(feature="t"))
    config: Any = {"configurable": {"thread_id": "t1"}}

    paused = await graph.ainvoke({"message": "everything is wrong"}, config, context=deps)

    assert paused["intent"] == "unclear" and "answer" not in paused
    assert large.requests == []  # nothing was sent to the expensive model yet
    assert (await graph.aget_state(config)).next == ("answer_large",)

    done = await graph.ainvoke(None, config, context=deps)  # a person approved: continue
    assert done["answer"] == "from large"
    assert len(large.requests) == 1


def test_the_graph_can_be_drawn() -> None:
    drawing = ROUTER_GRAPH.get_graph().draw_mermaid()
    for node in ("rules", "classify", "answer_known", "answer_large"):
        assert node in drawing
