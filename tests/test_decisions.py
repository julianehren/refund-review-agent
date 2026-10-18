"""Tests for the human-in-the-loop rules."""

import pytest

from refund_agent.decisions import DecisionError, record_decision, reset_decisions


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


def test_reset_decisions_reopens_only_reviewed_requests(conn):
    open_before = conn.execute("SELECT COUNT(*) FROM refund_requests WHERE status = 'open'").fetchone()[0]
    record_decision(conn, "R-1003", "APPROVE", "APPROVE")
    record_decision(conn, "R-1002", "REJECT", "REJECT")

    assert reset_decisions(conn) == 2
    assert conn.execute("SELECT COUNT(*) FROM refund_requests WHERE status = 'open'").fetchone()[0] == open_before
    assert conn.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0] == 0
