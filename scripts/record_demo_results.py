"""Record real agent runs for the online demo.

The hosted demo has no API key, so it replays these recorded results instead of
calling Claude live. Re-run this script whenever the agent, the policy or the
test cases change:

    python scripts/record_demo_results.py            # needs ANTHROPIC_API_KEY in .env
"""

import argparse
import json
import tempfile
from pathlib import Path

from refund_agent import config, db, seed
from refund_agent.agent import RefundReviewAgent
from refund_agent.demo import DEMO_RESULTS_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=config.DEFAULT_MODEL)
    args = parser.parse_args()

    # Fresh copy of the demo database, so every request is still open
    db_path = Path(tempfile.mkdtemp()) / "demo.db"
    seed.build_database(db_path)
    conn = db.connect(db_path)
    request_ids = [row["id"] for row in conn.execute(
        "SELECT id FROM refund_requests WHERE status = 'open' ORDER BY id")]

    agent = RefundReviewAgent(conn=conn, model=args.model)
    results = {}
    for request_id in request_ids:
        result = agent.review(request_id)
        decision = result.decision.decision if result.decision else f"ERROR: {result.error}"
        print(f"{request_id}: {decision}  (${result.cost_usd:.4f}, {result.latency_s:.1f}s)")
        results[request_id] = result.model_dump(mode="json")

    DEMO_RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nSaved {len(results)} results to {DEMO_RESULTS_PATH.relative_to(config.PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
