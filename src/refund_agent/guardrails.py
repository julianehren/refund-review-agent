"""Hard rules enforced in code, after the agent has decided.

The LLM handles judgment (which rules apply, how to read the customer's message).
Rules that are simple thresholds and expensive to get wrong are additionally
checked here, deterministically – so a missed search result can never turn
into a wrong approval.

Found in practice: in one recorded run the agent's policy search did not return
§9 (high-value requests) and it approved a 349 EUR refund that needs a
four-eyes review. This guardrail catches exactly that case.
"""

from refund_agent.models import RefundDecision

HIGH_VALUE_LIMIT_EUR = 250.00  # store policy §9 – keep in sync with data/store_policy.md

ESCALATION_REPLY = (
    "Thank you for your refund request. Because of the order value, it needs an additional review "
    "by our team. We will get back to you shortly. Kind regards, HomeCraft Kitchen customer service"
)


def apply_guardrails(decision: RefundDecision, amount_requested: float) -> tuple[RefundDecision, str | None]:
    """Return the (possibly corrected) decision and a note if a guardrail changed it.

    The agent's summary stays as written, so the reviewer still sees its original reasoning;
    the note is returned separately (AgentResult.guardrail).
    """
    if decision.decision == "APPROVE" and amount_requested > HIGH_VALUE_LIMIT_EUR:
        note = (f"Guardrail §9: {amount_requested:.2f} EUR is above {HIGH_VALUE_LIMIT_EUR:.2f} EUR, "
                f"so the agent's APPROVE was changed to ESCALATE (four-eyes review).")
        corrected = decision.model_copy(update={
            "decision": "ESCALATE",
            "cited_policies": [*decision.cited_policies, "§9"] if "§9" not in decision.cited_policies
            else decision.cited_policies,
            "customer_reply": ESCALATION_REPLY,
        })
        return corrected, note
    return decision, None
