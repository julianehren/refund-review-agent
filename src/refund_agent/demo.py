"""Demo mode: replay recorded agent runs instead of calling Claude live.

Used by the hosted online demo, which has no API key. The recordings are real
runs of the agent (scripts/record_demo_results.py) – nothing is hand-written.

Demo mode is on when REFUND_DEMO_MODE=1 is set, or automatically when no
ANTHROPIC_API_KEY is configured.
"""

import json
import os
from functools import cache

from refund_agent import config
from refund_agent.models import AgentResult

DEMO_RESULTS_PATH = config.PROJECT_ROOT / "data" / "demo_results.json"


def is_demo_mode() -> bool:
    if os.getenv("REFUND_DEMO_MODE", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return not os.getenv("ANTHROPIC_API_KEY")


@cache
def load_demo_results() -> dict[str, AgentResult]:
    raw = json.loads(DEMO_RESULTS_PATH.read_text(encoding="utf-8"))
    return {request_id: AgentResult.model_validate(result) for request_id, result in raw.items()}


def get_demo_result(request_id: str) -> AgentResult | None:
    return load_demo_results().get(request_id)
