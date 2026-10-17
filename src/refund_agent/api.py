"""REST API for the refund review agent (FastAPI).

Start the server:   uvicorn refund_agent.api:app --reload
Interactive docs:   http://localhost:8000/docs

The API offers the same workflow as the Streamlit UI, but for other programs
(a shop system, a helpdesk, an n8n workflow …):

    GET  /requests                    list refund requests
    GET  /requests/{id}               details of one request
    POST /reviews                     let the agent review a request
    POST /requests/{id}/decision      human reviewer records the final decision
    GET  /decisions                   audit log of all human decisions

No new business logic lives here: the endpoints only call the existing
building blocks (tools, agent, decisions). That is why the tools were written
without any knowledge of Streamlit or Claude.
"""

import os
import sqlite3
import threading
from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated, Literal

import anthropic
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from refund_agent import __version__, config, db, tools
from refund_agent.agent import RefundReviewAgent
from refund_agent.decisions import DecisionError, record_decision
from refund_agent.knowledge import PolicyIndex
from refund_agent.models import AgentResult, DecisionType

app = FastAPI(
    title="Refund Review Agent API",
    version=__version__,
    description="An AI agent that reviews e-commerce refund requests with tool use and RAG. "
                "The agent only recommends – a human records the final decision.",
)

# The latest agent result per request, kept in memory so a human can decide on it afterwards.
# (Simple on purpose: a production system would store this in the database.)
latest_reviews: dict[str, AgentResult] = {}


# --- Dependencies -----------------------------------------------------------------
# FastAPI calls these functions for every request and passes the result into the
# endpoint. Tests replace them (app.dependency_overrides) with fakes.

def get_db() -> Iterator[sqlite3.Connection]:
    """One database connection per HTTP request, closed afterwards."""
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


_policy_index: PolicyIndex | None = None
_policy_index_lock = threading.Lock()


def get_policy_index() -> PolicyIndex:
    """Loaded once: the embedding model is too slow to load for every request.

    The lock matters: n8n sends several requests at the same time. Without it,
    each parallel first request would try to open the Chroma database at once,
    which fails ("Could not connect to tenant default_tenant").
    """
    global _policy_index
    with _policy_index_lock:
        if _policy_index is None:
            _policy_index = PolicyIndex()
        return _policy_index


@lru_cache
def get_llm_client() -> anthropic.Anthropic:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(503, "ANTHROPIC_API_KEY is not configured on the server.")
    return anthropic.Anthropic()


DB = Annotated[sqlite3.Connection, Depends(get_db)]


# --- Request and response bodies ------------------------------------------------------

class ReviewCreate(BaseModel):
    request_id: str = Field(examples=["R-1003"])
    model: str = Field(default=config.DEFAULT_MODEL, description="Claude model the agent should use")


class DecisionCreate(BaseModel):
    decision: DecisionType = Field(description="The human's final decision")
    reviewer_note: str | None = Field(default=None, description="Required when overriding the agent")


class RequestSummary(BaseModel):
    id: str
    customer_name: str
    reason: str
    amount_requested: float
    submitted_at: str
    status: str


# --- Endpoints ------------------------------------------------------------------------

@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/requests", tags=["requests"])
def list_requests(conn: DB, status: Literal["open", "refunded", "rejected", "escalated", "all"] = Query("open")
                  ) -> list[RequestSummary]:
    """List refund requests (by default only the open ones waiting for review)."""
    sql = ("SELECT r.id, c.name AS customer_name, r.reason, r.amount_requested, r.submitted_at, r.status "
           "FROM refund_requests r JOIN customers c ON c.id = r.customer_id WHERE r.id NOT LIKE '%-H%'")
    params: tuple = ()
    if status != "all":
        sql += " AND r.status = ?"
        params = (status,)
    return [RequestSummary(**dict(row)) for row in conn.execute(sql + " ORDER BY r.id", params)]


@app.get("/requests/{request_id}", tags=["requests"])
def get_request(request_id: str, conn: DB) -> dict:
    """Details of one refund request (the same data the agent sees via its first tool)."""
    try:
        return tools.get_refund_request(conn, request_id)
    except tools.ToolError as exc:
        raise HTTPException(404, str(exc))


@app.post("/reviews", tags=["reviews"])
def create_review(body: ReviewCreate, conn: DB, index: Annotated[PolicyIndex, Depends(get_policy_index)],
                  client: Annotated[anthropic.Anthropic, Depends(get_llm_client)]) -> AgentResult:
    """Let the agent review an open request. Returns the recommendation, the full tool trace and the costs.

    Takes a few seconds, because the agent calls Claude several times.
    """
    request = get_request(body.request_id, conn)  # raises 404 if unknown
    if request["status"] != "open":
        raise HTTPException(409, f"Request {body.request_id} is already decided (status: {request['status']}).")
    agent = RefundReviewAgent(conn=conn, policy_index=index, client=client, model=body.model)
    result = agent.review(body.request_id)
    latest_reviews[body.request_id] = result
    return result


@app.post("/requests/{request_id}/decision", tags=["reviews"], status_code=201)
def create_decision(request_id: str, body: DecisionCreate, conn: DB) -> dict:
    """Human-in-the-loop: record the final decision for a request the agent has reviewed."""
    request = get_request(request_id, conn)  # raises 404 if unknown
    if request["status"] != "open":
        raise HTTPException(409, f"Request {request_id} is already decided (status: {request['status']}).")
    review = latest_reviews.get(request_id)
    if review is None or review.decision is None:
        raise HTTPException(409, f"Run POST /reviews for {request_id} first – the human decides on the agent's "
                                 f"recommendation.")
    try:
        saved = record_decision(conn, request_id, review.decision.decision, body.decision, body.reviewer_note,
                                review.model, review.cost_usd)
    except DecisionError as exc:
        raise HTTPException(409, str(exc))
    latest_reviews.pop(request_id, None)
    return saved


@app.get("/decisions", tags=["reviews"])
def list_decisions(conn: DB) -> list[dict]:
    """Audit log: every human decision next to the agent's recommendation."""
    return [dict(row) for row in conn.execute("SELECT * FROM review_decisions ORDER BY id DESC")]
