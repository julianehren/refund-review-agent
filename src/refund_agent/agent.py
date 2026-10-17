"""The refund review agent: Claude + tools in a loop.

The agentic loop in plain words:
1. Send Claude the task and the list of available tools.
2. Claude answers either with text or with "please call tool X with input Y".
3. We run the tool in Python and send the result back.
4. Repeat until Claude calls the special tool `submit_decision`, whose input
   must match the RefundDecision schema. That is the final answer.

Run one case from the command line:  python -m refund_agent.agent R-1003
"""

import json
import sqlite3
import sys
import time
from typing import Any

import anthropic
from pydantic import ValidationError

from refund_agent import config, db
from refund_agent.knowledge import SEARCH_POLICIES_SCHEMA, PolicyIndex
from refund_agent.models import AgentResult, RefundDecision, ToolCall
from refund_agent.tools import DATABASE_TOOL_SCHEMAS, DATABASE_TOOLS, ToolError

SYSTEM_PROMPT = """You are a refund review agent for the online shop "HomeCraft Kitchen".
Your job: review one refund request and recommend APPROVE, REJECT or ESCALATE.
A human from the customer service team makes the final decision based on your recommendation.

How to work:
1. Gather the facts with the database tools. Start with get_refund_request, then look up the order,
   the shipment and the customer history. Do not guess facts – if you did not get it from a tool, you do not know it.
2. Find the applicable rules with search_policies. Search for every relevant aspect of the case
   (the refund reason, the product type, the customer's history, payment disputes, the amount)
   and also search for the order of precedence between rules.
3. Apply the rules strictly as written. Never invent rules. If facts are missing or rules conflict, ESCALATE.
4. Finish by calling submit_decision. Cite only policy sections that search_policies returned to you.

Write the customer reply in English, polite and concise, without promising anything the decision does not cover."""

SUBMIT_DECISION_SCHEMA = {
    "name": "submit_decision",
    "description": "Submit your final recommendation. Call this exactly once, at the very end.",
    "input_schema": RefundDecision.model_json_schema(),
}


class RefundReviewAgent:
    def __init__(self, conn: sqlite3.Connection | None = None, policy_index: PolicyIndex | None = None,
                 client: Any = None, model: str = config.DEFAULT_MODEL):
        self.conn = conn or db.connect()
        self.policy_index = policy_index or PolicyIndex()
        self.client = client or anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
        self.model = model
        self.tool_schemas = [*DATABASE_TOOL_SCHEMAS, SEARCH_POLICIES_SCHEMA, SUBMIT_DECISION_SCHEMA]

    # --- running tools --------------------------------------------------------
    def _run_tool(self, name: str, tool_input: dict) -> tuple[Any, bool]:
        """Execute one tool. Returns (result, is_error). Errors are sent back to Claude, not raised."""
        try:
            if name == "search_policies":
                return self.policy_index.search(tool_input["query"]), False
            if name in DATABASE_TOOLS:
                return DATABASE_TOOLS[name](self.conn, **tool_input), False
            return f"Unknown tool {name!r}.", True
        except (ToolError, TypeError, KeyError) as exc:
            return f"Tool error: {exc}", True

    # --- the agent loop -------------------------------------------------------
    def review(self, request_id: str) -> AgentResult:
        messages: list[dict] = [{"role": "user", "content": f"Please review refund request {request_id}."}]
        trace: list[ToolCall] = []
        retrieved: list[str] = []
        input_tokens = output_tokens = llm_calls = 0
        decision: RefundDecision | None = None
        error: str | None = None
        reminded = False
        started = time.perf_counter()

        for _ in range(config.MAX_AGENT_STEPS):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=self.tool_schemas,
                messages=messages,
            )
            llm_calls += 1
            input_tokens += response.usage.input_tokens
            output_tokens += response.usage.output_tokens
            messages.append({"role": "assistant", "content": response.content})

            tool_uses = [block for block in response.content if block.type == "tool_use"]
            if not tool_uses:
                # Claude answered with plain text instead of submitting. Remind it once.
                if reminded:
                    error = "Agent stopped without submitting a decision."
                    break
                reminded = True
                messages.append({"role": "user", "content": "Please finish by calling submit_decision."})
                continue

            tool_results = []
            for block in tool_uses:
                t0 = time.perf_counter()
                if block.name == "submit_decision":
                    try:
                        decision = RefundDecision.model_validate(block.input)
                        output, is_error = "Decision recorded.", False
                    except ValidationError as exc:
                        # Structured output failed validation -> let Claude fix it in the next step.
                        output, is_error = f"Invalid decision, please fix and resubmit: {exc}", True
                else:
                    output, is_error = self._run_tool(block.name, block.input)
                    if block.name == "search_policies" and not is_error:
                        retrieved += [hit["section"] for hit in output if hit["section"] not in retrieved]

                trace.append(ToolCall(name=block.name, input=block.input, output=output, is_error=is_error,
                                      duration_ms=round((time.perf_counter() - t0) * 1000)))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(output, ensure_ascii=False, default=str),
                    "is_error": is_error,
                })

            if decision is not None:
                break
            messages.append({"role": "user", "content": tool_results})
        else:
            error = f"Agent did not finish within {config.MAX_AGENT_STEPS} steps."

        return AgentResult(
            request_id=request_id,
            decision=decision,
            trace=trace,
            retrieved_policies=retrieved,
            # Grounding check: did the agent only cite sections it actually retrieved?
            citations_grounded=bool(decision) and set(decision.cited_policies) <= set(retrieved),
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost(self.model, input_tokens, output_tokens),
            latency_s=round(time.perf_counter() - started, 2),
            llm_calls=llm_calls,
            error=error,
        )


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Cost in USD based on the price table in config.py (0 if the model is unknown)."""
    price_in, price_out = config.MODEL_PRICES_USD.get(model, (0.0, 0.0))
    return round((input_tokens * price_in + output_tokens * price_out) / 1_000_000, 6)


def _print_result(result: AgentResult) -> None:
    print(f"\n=== {result.request_id} ===")
    for step in result.trace:
        args = ", ".join(f"{k}={v!r}" for k, v in step.input.items()) if step.name != "submit_decision" else "…"
        print(f"  -> {step.name}({args}){'  [ERROR]' if step.is_error else ''}")
    if result.decision:
        d = result.decision
        print(f"\nDecision: {d.decision} (confidence: {d.confidence}) – cites {', '.join(d.cited_policies)}")
        print(f"Summary:  {d.summary}")
        print(f"Reply:    {d.customer_reply}")
    else:
        print(f"\nNo decision: {result.error}")
    print(f"\n{result.llm_calls} LLM calls · {result.input_tokens + result.output_tokens} tokens · "
          f"${result.cost_usd:.4f} · {result.latency_s}s · citations grounded: {result.citations_grounded}")


if __name__ == "__main__":
    agent = RefundReviewAgent()
    for rid in sys.argv[1:] or ["R-1003"]:
        _print_result(agent.review(rid))
