"""Human-in-the-loop review interface.

Start with:  streamlit run app/streamlit_app.py

The agent only RECOMMENDS. A human reviewer sees the recommendation, the
facts and the cited policy sections, and then accepts or overrides it.
Every final decision is written to the review_decisions audit table.

Without an ANTHROPIC_API_KEY (e.g. the hosted online demo) the app runs in demo
mode and replays recorded real agent runs instead of calling Claude.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Make the package importable when the project is not pip-installed (Streamlit Community Cloud)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from refund_agent import config, db  # noqa: E402
from refund_agent.decisions import DecisionError, record_decision, reset_decisions  # noqa: E402
from refund_agent.demo import get_demo_result, is_demo_mode  # noqa: E402
from refund_agent.policy import load_policy_sections  # noqa: E402

REPO_URL = "https://github.com/julianehren/refund-review-agent"
DEMO = is_demo_mode()

# Guided tour for the online demo: three cases that show the most interesting behaviour
TOUR = [
    ("R-1003", "✅ Clear approval", "Parcel arrived damaged, photo attached"),
    ("R-1015", "⚠️ Suspicious history", "Lost parcel, but 2 earlier \"not received\" claims"),
    ("R-1013", "🛡️ Guardrail", "Agent approves 349 €, code enforces four-eyes review"),
]


def select_request(request_id: str) -> None:
    st.session_state.selected_request = request_id

st.set_page_config(page_title="Refund Review Agent", page_icon="🧾", layout="wide")

DECISION_STYLE = {"APPROVE": ("✅", "green"), "REJECT": ("⛔", "red"), "ESCALATE": ("⚠️", "orange")}
REASON_LABELS = {
    "changed_mind": "Changed mind", "damaged_in_transit": "Damaged in transit", "defective": "Defective",
    "not_received": "Not received", "wrong_item": "Wrong item",
}


# --- cached resources (created once per server, not on every click) -------------
@st.cache_resource
def get_connection():
    if not config.DB_PATH.exists():
        from refund_agent import seed

        seed.build_database()
        seed.write_labels()
    return db.connect()


@st.cache_resource(show_spinner="Loading knowledge base (first start downloads the embedding model) …")
def get_agent(model: str):
    from refund_agent.agent import RefundReviewAgent  # imported lazily: the demo does not need Chroma

    return RefundReviewAgent(conn=get_connection(), model=model)


@st.cache_data
def get_policy_sections() -> dict[str, dict]:
    return {s["section"]: s for s in load_policy_sections()}


conn = get_connection()
st.session_state.setdefault("results", {})

# --- sidebar: queue and settings -----------------------------------------------
with st.sidebar:
    st.header("🧾 Review queue")
    show_all = st.toggle("Show already decided requests", value=False)
    query = "SELECT r.id, r.reason, r.amount_requested, r.status, c.name FROM refund_requests r " \
            "JOIN customers c ON c.id = r.customer_id WHERE r.id NOT LIKE '%-H%'"
    if not show_all:
        query += " AND r.status = 'open'"
    queue = conn.execute(query + " ORDER BY r.id").fetchall()

    if not queue:
        st.success("Queue is empty – all requests are decided.")
        st.stop()

    def label(row) -> str:
        done = "" if row["status"] == "open" else f" · {row['status']}"
        # Note: the label must not change while a request is selected – Streamlit would treat
        # the radio as a new widget and jump back to the first entry.
        return f"{row['id']} · {REASON_LABELS[row['reason']]} · {row['amount_requested']:.2f} €{done}"

    rows = {row["id"]: row for row in queue}
    request_id = st.radio("Open requests", list(rows), format_func=lambda rid: label(rows[rid]),
                          label_visibility="collapsed", key="selected_request")

    st.divider()
    if DEMO:
        model = config.DEFAULT_MODEL
        st.caption(f"**Demo mode** · recorded runs of `{model}`")
        if st.button("🔄 Reset demo data", help="Reopen all requests and clear the audit log"):
            reset_decisions(conn)
            st.session_state.results = {}
            st.session_state.flash = "Demo data reset – all requests are open again."
            st.rerun()
    else:
        model = st.selectbox("Model", list(config.MODEL_PRICES_USD), index=0,
                             help="Haiku is the cheapest; Sonnet and Opus are stronger but cost more.")
    st.caption(f"Simulation date: {config.AS_OF_DATE.isoformat()}")
    st.caption(f"[Source code on GitHub]({REPO_URL})")

# --- main area: request details ------------------------------------------------
request = conn.execute(
    "SELECT r.*, c.name AS customer_name, s.delivered_at, s.status AS shipment_status "
    "FROM refund_requests r JOIN customers c ON c.id = r.customer_id "
    "JOIN shipments s ON s.order_id = r.order_id WHERE r.id = ?",
    (request_id,),
).fetchone()

if DEMO:
    st.info(
        "**Online demo** – an AI agent reviews refund requests, a human makes the final call. "
        "Pick a request, click **Run agent** and accept or override the recommendation. "
        "To keep the demo free, the agent's answers are **replays of real recorded runs** "
        "(Claude Haiku, tool use + RAG) – no live AI calls. Decisions go into a shared demo database. "
        f"[How it works → GitHub]({REPO_URL})",
        icon="👋",
    )

    open_ids = {r["id"] for r in conn.execute("SELECT id FROM refund_requests WHERE status = 'open'")}
    st.markdown("**Try these three cases:**")
    for column, (tour_id, title, hint) in zip(st.columns(len(TOUR)), TOUR):
        with column:
            st.button(f"{title} · {tour_id}", key=f"tour_{tour_id}", on_click=select_request, args=(tour_id,),
                      disabled=tour_id not in open_ids, use_container_width=True,
                      help=None if tour_id in open_ids else "Already decided – use 'Reset demo data' in the sidebar")
            st.caption(hint)

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

st.title(f"Refund request {request_id}")
col1, col2, col3, col4 = st.columns([1.5, 1, 1, 0.7])
col1.metric("Reason", REASON_LABELS[request["reason"]])
col2.metric("Amount", f"{request['amount_requested']:.2f} €")
col3.metric("Submitted", request["submitted_at"])
col4.metric("Photo", "Yes" if request["photo_attached"] else "No")
st.markdown(f"**{request['customer_name']}** wrote:")
st.info(request["customer_message"])
st.caption(f"Order {request['order_id']} · shipment status: {request['shipment_status']}"
           f"{' · delivered ' + request['delivered_at'] if request['delivered_at'] else ''}")

# --- run the agent ---------------------------------------------------------------
if st.button("🤖 Run agent", type="primary", disabled=request["status"] != "open"):
    if DEMO:
        recorded = get_demo_result(request_id)
        if recorded is None:
            st.warning("No recorded run for this request in the demo.")
            st.stop()
        st.session_state.results[request_id] = recorded
    else:
        with st.spinner("The agent is gathering facts and searching the policy …"):
            st.session_state.results[request_id] = get_agent(model).review(request_id)

result = st.session_state.results.get(request_id)
if result is None:
    st.caption("Click **Run agent** to get a recommendation.")
    st.stop()

if result.decision is None:
    st.error(f"The agent did not produce a decision: {result.error}")
    st.stop()

# --- recommendation ---------------------------------------------------------------
decision = result.decision
icon, color = DECISION_STYLE[decision.decision]
st.divider()
st.subheader("Agent recommendation")
st.markdown(f"## :{color}[{icon} {decision.decision}]  \n*confidence: {decision.confidence}*")
st.write(decision.summary)
if result.guardrail:
    st.warning(f"🛡️ {result.guardrail}")

left, right = st.columns([3, 2])
with left:
    st.markdown("**Key facts**")
    for fact in decision.key_facts:
        st.markdown(f"- {fact}")
    st.markdown("**Cited policy sections**")
    policies = get_policy_sections()
    for section in decision.cited_policies:
        policy = policies.get(section)
        with st.expander(f"{section} {policy['title']}" if policy else f"{section} (unknown section)"):
            st.markdown(policy["text"] if policy else "_Section not found in policy._")
    if not result.citations_grounded:
        st.warning("The agent cited a section it did not retrieve via search – check the reasoning carefully.")

with right:
    m1, m2 = st.columns(2)
    m1.metric("Cost", f"${result.cost_usd:.4f}")
    m2.metric("Latency", f"{result.latency_s:.1f} s")
    m1.metric("Tokens", f"{result.input_tokens + result.output_tokens:,}")
    m2.metric("Tool calls", len(result.trace))
    st.caption(f"Model: {result.model} · LLM calls: {result.llm_calls}"
               + (" · recorded run (replay)" if DEMO else ""))

with st.expander("🔍 Agent trace – every tool call with input and output"):
    for n, step in enumerate(result.trace, start=1):
        st.markdown(f"**{n}. `{step.name}`** {'⚠️ error' if step.is_error else ''} · {step.duration_ms} ms")
        st.code(json.dumps(step.input, indent=2, ensure_ascii=False), language="json")
        if step.name != "submit_decision":
            st.json(step.output, expanded=False)

# --- human decision ---------------------------------------------------------------
st.divider()
st.subheader("👤 Your decision")
options = ["APPROVE", "REJECT", "ESCALATE"]
human = st.radio("Final decision", options, index=options.index(decision.decision), horizontal=True,
                 help="Pre-selected with the agent's recommendation. Change it to override.")
reply = st.text_area("Reply to the customer", value=decision.customer_reply, height=100)
note = st.text_input("Internal note (optional)",
                     placeholder="Required when you override the agent" if human != decision.decision else "")

if human != decision.decision:
    st.warning(f"You are overriding the agent ({decision.decision} → {human}).")

if st.button("Submit decision", type="primary"):
    try:
        record_decision(conn, request_id, decision.decision, human, note, result.model, result.cost_usd)
    except DecisionError as exc:
        st.error(str(exc))
    else:
        st.session_state.flash = f"Saved: {request_id} → {human}. The reply was sent to the customer (simulated)."
        st.rerun()

# --- audit log ---------------------------------------------------------------------
with st.expander("📋 Audit log – all human decisions"):
    log = pd.read_sql_query("SELECT * FROM review_decisions ORDER BY id DESC", conn)
    if log.empty:
        st.caption("No decisions yet.")
    else:
        agreement = (log.agent_decision == log.human_decision).mean()
        st.metric("Agreement human ↔ agent", f"{agreement:.0%}")
        st.dataframe(log, hide_index=True, use_container_width=True)
