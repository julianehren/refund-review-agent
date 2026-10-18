"""Tests for the hard rules that are checked in code after the agent decided."""

from refund_agent.agent import RefundReviewAgent
from refund_agent.guardrails import apply_guardrails
from refund_agent.models import RefundDecision
from tests.test_agent import VALID_DECISION, FakeClient, index, response, tool_use  # noqa: F401 (fixture)


def decision(**changes) -> RefundDecision:
    return RefundDecision.model_validate({**VALID_DECISION, **changes})


def test_high_value_approval_is_escalated():
    corrected, note = apply_guardrails(decision(), amount_requested=349.00)
    assert corrected.decision == "ESCALATE"
    assert "§9" in corrected.cited_policies
    assert "approved" not in corrected.customer_reply.lower()
    assert note.startswith("Guardrail §9")


def test_low_value_approval_is_unchanged():
    original = decision()
    corrected, note = apply_guardrails(original, amount_requested=49.90)
    assert corrected == original and note is None


def test_limit_itself_is_not_high_value():
    _, note = apply_guardrails(decision(), amount_requested=250.00)  # policy: "above 250.00 EUR"
    assert note is None


def test_high_value_rejection_is_unchanged():
    _, note = apply_guardrails(decision(decision="REJECT"), amount_requested=349.00)
    assert note is None


def test_agent_applies_guardrail_regression_r1013(conn, index):
    # Regression test: a recorded run approved the 349 EUR stand mixer (R-1013) without citing §9.
    client = FakeClient([response(tool_use("submit_decision", {
        **VALID_DECISION, "request_id": "R-1013", "cited_policies": ["§4"]}, 1))])
    result = RefundReviewAgent(conn, index, client).review("R-1013")
    assert result.decision.decision == "ESCALATE"
    assert result.guardrail is not None
    assert result.citations_grounded is False  # grounding is judged on the agent's own citations
