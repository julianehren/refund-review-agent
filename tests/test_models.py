"""Tests for the decision model."""

from refund_agent.models import RefundDecision
from tests.test_agent import VALID_DECISION


def test_leftover_tags_are_removed_from_text_fields():
    """Regression: the model once ended a customer reply with '</customer_reply>' (found via Claude Desktop)."""
    decision = RefundDecision.model_validate({
        **VALID_DECISION,
        "customer_reply": "We have started an investigation with the carrier.\n</customer_reply>",
        "summary": "<summary>Escalate under §6.</summary>",
        "key_facts": ["Tracking says delivered</key_facts>"],
    })
    assert decision.customer_reply == "We have started an investigation with the carrier."
    assert decision.summary == "Escalate under §6."
    assert decision.key_facts == ["Tracking says delivered"]


def test_normal_text_is_unchanged():
    decision = RefundDecision.model_validate({**VALID_DECISION, "summary": "Amount < 250 EUR and > 0, see §9."})
    assert decision.summary == "Amount < 250 EUR and > 0, see §9."
