"""The human-in-the-loop step: recording the final decision of a human reviewer.

Used by both the Streamlit UI and the REST API, so the rules live in one place.
"""

import sqlite3

STATUS_FOR_DECISION = {"APPROVE": "refunded", "REJECT": "rejected", "ESCALATE": "escalated"}


class DecisionError(ValueError):
    """The decision cannot be recorded (e.g. request already decided, override without a note)."""


def record_decision(conn: sqlite3.Connection, request_id: str, agent_decision: str, human_decision: str,
                    reviewer_note: str | None = None, model: str | None = None,
                    cost_usd: float | None = None) -> dict:
    """Store the human decision in the audit log and close the refund request.

    Rules (four-eyes principle):
    - only open requests can be decided
    - overriding the agent requires a note explaining why
    """
    if human_decision not in STATUS_FOR_DECISION:
        raise DecisionError(f"Unknown decision {human_decision!r}.")
    row = conn.execute("SELECT status FROM refund_requests WHERE id = ?", (request_id,)).fetchone()
    if row is None:
        raise DecisionError(f"No refund request with id {request_id!r}.")
    if row["status"] != "open":
        raise DecisionError(f"Request {request_id} is already decided (status: {row['status']}).")
    note = (reviewer_note or "").strip() or None
    if human_decision != agent_decision and note is None:
        raise DecisionError("Overriding the agent requires a reviewer note.")

    cursor = conn.execute(
        "INSERT INTO review_decisions (request_id, agent_decision, human_decision, reviewer_note, model, cost_usd) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (request_id, agent_decision, human_decision, note, model, cost_usd),
    )
    conn.execute("UPDATE refund_requests SET status = ? WHERE id = ?", (STATUS_FOR_DECISION[human_decision], request_id))
    conn.commit()
    return dict(conn.execute("SELECT * FROM review_decisions WHERE id = ?", (cursor.lastrowid,)).fetchone())


def reset_decisions(conn: sqlite3.Connection) -> int:
    """Undo all human decisions: reopen the requests and clear the audit log (used by the online demo).

    Returns the number of reopened requests. Historic requests (not decided via the review) stay untouched.
    """
    cursor = conn.execute(
        "UPDATE refund_requests SET status = 'open' WHERE id IN (SELECT request_id FROM review_decisions)")
    conn.execute("DELETE FROM review_decisions")
    conn.commit()
    return cursor.rowcount
