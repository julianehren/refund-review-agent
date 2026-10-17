"""Tests for the agent loop – without calling the real Claude API.

A FakeClient plays Claude's role with pre-scripted answers. This tests OUR
logic: tool dispatch, error handling, validation, grounding check, token
counting. (How good Claude's decisions are is measured by evals/, not here.)
"""

from types import SimpleNamespace

import pytest

from refund_agent.agent import RefundReviewAgent, estimate_cost
from refund_agent.knowledge import PolicyIndex
from tests.test_knowledge import WordCountEmbedding

VALID_DECISION = {
    "request_id": "R-1003",
    "decision": "APPROVE",
    "confidence": "high",
    "summary": "Transport damage reported within 7 days with a photo.",
    "key_facts": ["Reported 2 days after delivery", "Photo attached"],
    "cited_policies": ["§5"],
    "customer_reply": "We are sorry – your refund is on its way.",
}


def tool_use(name, tool_input, n):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=f"tool_{n}")


def response(*blocks):
    return SimpleNamespace(content=list(blocks), usage=SimpleNamespace(input_tokens=1000, output_tokens=100))


class FakeClient:
    """Returns the scripted responses one after another and records what it was sent."""

    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self._responses)


@pytest.fixture
def index():
    return PolicyIndex(embedding_function=WordCountEmbedding(), persist_dir=None)


def test_agent_runs_tools_and_returns_decision(conn, index):
    client = FakeClient([
        response(tool_use("get_refund_request", {"request_id": "R-1003"}, 1)),
        response(tool_use("search_policies", {"query": "Damaged in transit photo"}, 2)),
        response(tool_use("submit_decision", VALID_DECISION, 3)),
    ])
    result = RefundReviewAgent(conn, index, client, model="claude-haiku-5-5").review("R-1003")

    assert result.decision.decision == "APPROVE"
    assert [s.name for s in result.trace] == ["get_refund_request", "search_policies", "submit_decision"]
    assert result.trace[0].output["reason"] == "damaged_in_transit"  # real data from the database
    assert result.llm_calls == 3
    assert result.input_tokens == 3000 and result.output_tokens == 300
    assert result.error is None


def test_citation_not_retrieved_is_flagged_as_ungrounded(conn, index):
    client = FakeClient([response(tool_use("submit_decision", VALID_DECISION, 1))])  # cites §5 without searching
    result = RefundReviewAgent(conn, index, client).review("R-1003")
    assert result.decision is not None
    assert result.citations_grounded is False


def test_invalid_decision_is_sent_back_for_correction(conn, index):
    client = FakeClient([
        response(tool_use("submit_decision", {**VALID_DECISION, "decision": "MAYBE"}, 1)),
        response(tool_use("submit_decision", VALID_DECISION, 2)),
    ])
    result = RefundReviewAgent(conn, index, client).review("R-1003")
    assert result.trace[0].is_error is True
    assert result.decision.decision == "APPROVE"


def test_tool_errors_are_reported_to_the_model_not_raised(conn, index):
    client = FakeClient([
        response(tool_use("get_order", {"order_id": "O-0000"}, 1)),
        response(tool_use("submit_decision", VALID_DECISION, 2)),
    ])
    result = RefundReviewAgent(conn, index, client).review("R-1003")
    assert result.trace[0].is_error is True
    # messages = [task, Claude's tool call, our tool result, ...]
    tool_result = client.calls[1]["messages"][2]["content"][0]
    assert tool_result["is_error"] is True and "No order" in tool_result["content"]


def test_agent_stops_when_model_never_submits(conn, index):
    text = SimpleNamespace(type="text", text="I think it should be approved.")
    client = FakeClient([response(text), response(text)])
    result = RefundReviewAgent(conn, index, client).review("R-1003")
    assert result.decision is None
    assert "without submitting" in result.error


def test_cost_estimate():
    # 1M input tokens at $0.10 + 1M output tokens at $0.50
    assert estimate_cost("claude-haiku-5-5", 1_000_000, 1_000_000) == pytest.approx(0.60)
    assert estimate_cost("unknown-model", 1000, 1000) == 0.0
