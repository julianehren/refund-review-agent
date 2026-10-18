"""Tests for the MCP server – tools are called the way Claude Desktop would call them."""

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from refund_agent import config, knowledge, mcp_server, seed
from refund_agent.agent import RefundReviewAgent
from refund_agent.knowledge import PolicyIndex
from tests.test_agent import VALID_DECISION, FakeClient, response, tool_use
from tests.test_knowledge import WordCountEmbedding


@pytest.fixture(autouse=True)
def test_setup(tmp_path, monkeypatch):
    db_path = tmp_path / "mcp_test.db"
    seed.build_database(db_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(knowledge, "_shared_index",
                        PolicyIndex(embedding_function=WordCountEmbedding(), persist_dir=None))
    mcp_server.latest_reviews.clear()


def call(name: str, **arguments):
    """Call a tool like an MCP client does; returns (is_error, parsed result or error text)."""
    try:
        result = asyncio.run(mcp_server.server.call_tool(name, arguments))
    except ToolError as exc:  # expected errors: the MCP client receives this message
        return True, str(exc)
    text = result.content[0].text if result.content else ""
    if result.is_error:
        return True, text
    data = result.structured_content
    if isinstance(data, dict) and set(data) == {"result"}:  # lists are wrapped as {"result": [...]}
        data = data["result"]
    return False, data if data is not None else json.loads(text)


def test_all_tools_are_listed_with_descriptions():
    listed = asyncio.run(mcp_server.server.list_tools())
    names = {tool.name for tool in listed}
    assert names == {"list_open_requests", "get_refund_request", "get_order", "get_shipment",
                     "get_customer_history", "search_policies", "run_agent_review", "record_human_decision"}
    assert all(tool.description for tool in listed)


def test_read_only_tools_return_shop_data():
    is_error, requests = call("list_open_requests")
    assert not is_error and len(requests) == 24

    is_error, request = call("get_refund_request", request_id="R-1016")
    assert not is_error and request["reason"] == "defective"

    is_error, order = call("get_order", order_id=request["order_id"])
    assert not is_error and len(order["payment_disputes"]) == 1


def test_unknown_id_returns_error_instead_of_crashing():
    is_error, message = call("get_refund_request", request_id="R-9999")
    assert is_error and "R-9999" in message


def test_search_policies():
    is_error, hits = call("search_policies", query="chargebacks payment dispute bank")
    assert not is_error and hits[0]["section"] == "§11"


def test_decision_requires_agent_review_first():
    is_error, message = call("record_human_decision", request_id="R-1003", decision="APPROVE")
    assert is_error and "run_agent_review" in message


def test_full_workflow(monkeypatch):
    fake = FakeClient([
        response(tool_use("get_refund_request", {"request_id": "R-1003"}, 1)),
        response(tool_use("submit_decision", VALID_DECISION, 2)),
    ])
    monkeypatch.setattr("refund_agent.agent.RefundReviewAgent",
                        lambda conn, policy_index: RefundReviewAgent(conn, policy_index, fake))

    is_error, review = call("run_agent_review", request_id="R-1003")
    assert not is_error and review["recommendation"]["decision"] == "APPROVE"

    is_error, message = call("record_human_decision", request_id="R-1003", decision="REJECT")
    assert is_error and "note" in message  # override without a note is refused

    is_error, saved = call("record_human_decision", request_id="R-1003", decision="APPROVE")
    assert not is_error and saved["human_decision"] == "APPROVE"

    is_error, requests = call("list_open_requests")
    assert "R-1003" not in {r["id"] for r in requests}
