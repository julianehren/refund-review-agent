"""MCP server: makes the shop tools usable from AI assistants like Claude Desktop.

MCP (Model Context Protocol) is an open standard for connecting AI assistants
to tools and data – a "USB port for AI". This server offers the SAME functions
the agent already uses (tools.py, knowledge.py), plus two workflow tools:
running our own review agent and recording the human decision.

Start (normally Claude Desktop starts it for you, see README):
    python -m refund_agent.mcp_server

Communication runs over stdin/stdout (the "stdio" transport), so this module
must never print anything to stdout itself.
"""

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as MCPToolError
from mcp.types import ToolAnnotations

from refund_agent import __version__, db, tools
from refund_agent.decisions import DecisionError, record_decision
from refund_agent.knowledge import get_shared_policy_index
from refund_agent.models import AgentResult

INSTRUCTIONS = """You are connected to the refund system of the online shop "HomeCraft Kitchen".
Typical workflow: list_open_requests → look at a request with get_refund_request, get_order,
get_shipment and get_customer_history → find the applicable rules with search_policies (cite them as §N)
→ optionally get a second opinion with run_agent_review → record_human_decision ONLY after the user
has explicitly confirmed the final decision. Never decide on the user's behalf."""

server = MCPServer(name="refund-review-agent", version=__version__, instructions=INSTRUCTIONS)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

# Latest agent recommendation per request (needed to log agent vs. human decision).
latest_reviews: dict[str, AgentResult] = {}

_DESCRIPTIONS = {schema["name"]: schema["description"] for schema in tools.DATABASE_TOOL_SCHEMAS}


def _call(tool, *args) -> Any:
    """Run a database tool with a fresh connection; turn ToolError into an error message the client sees.

    MCPToolError marks an expected error (e.g. unknown id): the client gets the message text.
    Any other exception counts as a crash and its details stay on the server.
    """
    conn = db.connect()
    try:
        return tool(conn, *args)
    except tools.ToolError as exc:
        raise MCPToolError(str(exc)) from exc
    finally:
        conn.close()


# --- Read-only tools: the same functions the agent uses -----------------------------

@server.tool(annotations=READ_ONLY)
def list_open_requests() -> list[dict]:
    """List all refund requests that are still waiting for a decision (id, customer, reason, amount)."""
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT r.id, c.name AS customer_name, r.reason, r.amount_requested, r.submitted_at "
            "FROM refund_requests r JOIN customers c ON c.id = r.customer_id "
            "WHERE r.status = 'open' AND r.id NOT LIKE '%-H%' ORDER BY r.id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@server.tool(description=_DESCRIPTIONS["get_refund_request"], annotations=READ_ONLY)
def get_refund_request(request_id: str) -> dict:
    return _call(tools.get_refund_request, request_id)


@server.tool(description=_DESCRIPTIONS["get_order"], annotations=READ_ONLY)
def get_order(order_id: str) -> dict:
    return _call(tools.get_order, order_id)


@server.tool(description=_DESCRIPTIONS["get_shipment"], annotations=READ_ONLY)
def get_shipment(order_id: str) -> dict:
    return _call(tools.get_shipment, order_id)


@server.tool(description=_DESCRIPTIONS["get_customer_history"], annotations=READ_ONLY)
def get_customer_history(customer_id: str, current_request_id: str) -> dict:
    return _call(tools.get_customer_history, customer_id, current_request_id)


@server.tool(annotations=READ_ONLY)
def search_policies(query: str) -> list[dict]:
    """Semantic search in the shop's refund policy. Returns the most relevant sections (e.g. '§5')
    with their text. Cite the section ids when you explain a decision."""
    return get_shared_policy_index().search(query)


# --- Workflow tools -----------------------------------------------------------------------

@server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
def run_agent_review(request_id: str) -> dict:
    """Let the shop's own review agent (a separate Claude-based agent) review the request and return
    its recommendation: decision, summary, key facts, cited policies, cost and number of tool calls.
    Calls the Claude API and costs a fraction of a cent. Does not change any data."""
    from refund_agent.agent import RefundReviewAgent  # imported lazily: needs the API key

    conn = db.connect()
    try:
        _call(tools.get_refund_request, request_id)  # raises a clear error for unknown ids
        result = RefundReviewAgent(conn=conn, policy_index=get_shared_policy_index()).review(request_id)
    finally:
        conn.close()
    latest_reviews[request_id] = result
    return {
        "request_id": request_id,
        "recommendation": result.decision.model_dump() if result.decision else None,
        "error": result.error,
        "tool_calls": [step.name for step in result.trace],
        "citations_grounded": result.citations_grounded,
        "cost_usd": result.cost_usd,
        "latency_s": result.latency_s,
    }


@server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False))
def record_human_decision(request_id: str, decision: Literal["APPROVE", "REJECT", "ESCALATE"],
                          reviewer_note: str | None = None) -> dict:
    """Record the FINAL human decision for a request and close it. Only call this after the user has
    explicitly confirmed the decision. Requires run_agent_review first; overriding the agent's
    recommendation requires a reviewer_note."""
    review = latest_reviews.get(request_id)
    if review is None or review.decision is None:
        raise MCPToolError(f"Run run_agent_review for {request_id} first – the human decides on the agent's "
                         f"recommendation.")
    conn = db.connect()
    try:
        saved = record_decision(conn, request_id, review.decision.decision, decision, reviewer_note,
                                review.model, review.cost_usd)
    except DecisionError as exc:
        raise MCPToolError(str(exc)) from exc
    finally:
        conn.close()
    latest_reviews.pop(request_id, None)
    return saved


def main() -> None:
    server.run()  # stdio transport: Claude Desktop talks to us via stdin/stdout


if __name__ == "__main__":
    main()
