"""Tests for the evaluation metrics (pure arithmetic, no API calls)."""

from evals.run_eval import compute_metrics


def row(expected, predicted, policy_hit=True, grounded=True):
    return {"expected": expected, "predicted": predicted, "correct": expected == predicted,
            "policy_hit": policy_hit, "grounded": grounded, "cost_usd": 0.01, "latency_s": 2.0,
            "tool_calls": 5, "input_tokens": 900, "output_tokens": 100}


def test_metrics():
    rows = [row("APPROVE", "APPROVE"), row("REJECT", "APPROVE", policy_hit=False),
            row("ESCALATE", "ESCALATE"), row("REJECT", "REJECT", grounded=False)]
    m = compute_metrics(rows)
    assert m["accuracy"] == 0.75
    assert m["wrong_approvals"] == 1
    assert m["per_class"]["APPROVE"] == {"precision": 0.5, "recall": 1.0, "support": 1}
    assert m["per_class"]["REJECT"]["recall"] == 0.5
    assert m["policy_hit_rate"] == 0.75
    assert m["grounding_rate"] == 0.75
    assert m["avg_tokens"] == 1000
    assert m["confusion"]["REJECT->APPROVE"] == 1
