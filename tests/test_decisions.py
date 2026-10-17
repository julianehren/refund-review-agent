"""Tests for the human-in-the-loop rules."""

import pytest

from refund_agent.decisions import DecisionError, record_decision


def test_decision_is_logged_and_closes_request(conn):
    saved = record_decision(conn, "R-1001", "APPROVE", "APPROVE")
    assert saved["human_decision"] == "APPROVE"
    status = conn.execute("SELECT status FROM refund_requests WHERE id = 'R-1001'").fetchone()["status"]
    assert status == "refunded"


def test_override_without_note_is_refused(conn):
    with pytest.raises(DecisionError, match="note"):
        record_decision(conn, "R-1001", "APPROVE", "REJECT", reviewer_note="   ")


def test_request_cannot_be_decided_twice(conn):
    record_decision(conn, "R-1001", "APPROVE", "APPROVE")
    with pytest.raises(DecisionError, match="already decided"):
        record_decision(conn, "R-1001", "APPROVE", "APPROVE")
