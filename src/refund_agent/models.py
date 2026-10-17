"""Data structures (Pydantic models) for the agent's input and output.

Pydantic validates data: if Claude returns a decision that does not match
RefundDecision (e.g. decision="MAYBE"), validation fails and the agent is
asked to correct itself. This is what "structured output" means in practice.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

DecisionType = Literal["APPROVE", "REJECT", "ESCALATE"]


class RefundDecision(BaseModel):
    """The final, structured recommendation of the agent."""

    request_id: str = Field(description="The id of the reviewed refund request, e.g. 'R-1001'")
    decision: DecisionType = Field(description="APPROVE, REJECT or ESCALATE")
    confidence: Literal["low", "medium", "high"] = Field(description="How sure you are about the decision")
    summary: str = Field(description="One or two sentences explaining the decision for the human reviewer")
    key_facts: list[str] = Field(description="The facts from the tools that the decision is based on")
    cited_policies: list[str] = Field(description="Policy section ids the decision relies on, e.g. ['§5', '§13']")
    customer_reply: str = Field(description="A short, friendly draft reply to the customer")


class ToolCall(BaseModel):
    """One step of the agent: which tool it called, with what, and what came back."""

    name: str
    input: dict[str, Any]
    output: Any
    is_error: bool = False
    duration_ms: int


class AgentResult(BaseModel):
    """Everything the agent produced for one refund request – decision plus audit trail and metrics."""

    request_id: str
    decision: RefundDecision | None
    trace: list[ToolCall]
    retrieved_policies: list[str]
    citations_grounded: bool
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_s: float
    llm_calls: int
    error: str | None = None
