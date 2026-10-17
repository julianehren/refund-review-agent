"""Tests for the REST API.

FastAPI's TestClient sends real HTTP requests to the app, but without starting
a server. The database, the policy index and the Claude client are replaced
with test versions via dependency_overrides – no API key needed.
"""

import pytest
from fastapi.testclient import TestClient

from refund_agent import api, db, seed
from refund_agent.knowledge import PolicyIndex
from tests.test_agent import VALID_DECISION, FakeClient, response, tool_use
from tests.test_knowledge import WordCountEmbedding


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "api_test.db"
    seed.build_database(db_path)

    def test_db():
        conn = db.connect(db_path)
        yield conn
        conn.close()

    fake_llm = FakeClient([
        response(tool_use("get_refund_request", {"request_id": "R-1003"}, 1)),
        response(tool_use("search_policies", {"query": "Damaged in transit photo"}, 2)),
        response(tool_use("submit_decision", VALID_DECISION, 3)),
    ])
    api.app.dependency_overrides = {
        api.get_db: test_db,
        api.get_policy_index: lambda: PolicyIndex(embedding_function=WordCountEmbedding(), persist_dir=None),
        api.get_llm_client: lambda: fake_llm,
    }
    api.latest_reviews.clear()
    yield TestClient(api.app)
    api.app.dependency_overrides = {}


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_list_open_requests(client):
    requests = client.get("/requests").json()
    assert len(requests) == 24
    assert requests[0]["id"] == "R-1001"


def test_get_unknown_request_returns_404(client):
    assert client.get("/requests/R-9999").status_code == 404


def test_full_workflow_review_then_human_decision(client):
    review = client.post("/reviews", json={"request_id": "R-1003"})
    assert review.status_code == 200
    assert review.json()["decision"]["decision"] == "APPROVE"
    assert [step["name"] for step in review.json()["trace"]][-1] == "submit_decision"

    decision = client.post("/requests/R-1003/decision", json={"decision": "APPROVE"})
    assert decision.status_code == 201
    assert decision.json()["human_decision"] == "APPROVE"

    assert client.get("/requests/R-1003").json()["status"] == "refunded"
    assert len(client.get("/decisions").json()) == 1
    # a decided request can neither be reviewed nor decided again
    assert client.post("/reviews", json={"request_id": "R-1003"}).status_code == 409
    second = client.post("/requests/R-1003/decision", json={"decision": "REJECT", "reviewer_note": "x"})
    assert second.status_code == 409 and "already decided" in second.json()["detail"]


def test_decision_without_review_is_rejected(client):
    assert client.post("/requests/R-1003/decision", json={"decision": "APPROVE"}).status_code == 409


def test_override_requires_note(client):
    client.post("/reviews", json={"request_id": "R-1003"})
    without_note = client.post("/requests/R-1003/decision", json={"decision": "REJECT"})
    assert without_note.status_code == 409
    with_note = client.post("/requests/R-1003/decision",
                            json={"decision": "REJECT", "reviewer_note": "Photo shows old damage"})
    assert with_note.status_code == 201
    assert with_note.json()["agent_decision"] == "APPROVE"


def test_invalid_decision_value_is_rejected(client):
    assert client.post("/requests/R-1003/decision", json={"decision": "MAYBE"}).status_code == 422
