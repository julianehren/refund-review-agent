"""The tools the agent can use to look up facts in the shop database.

Every tool is a plain Python function: it takes a database connection plus
simple arguments and returns a JSON-serialisable dict. The tools know nothing
about Claude, Streamlit or the agent – so the same functions can later be
reused by a REST API or an MCP server.

Date arithmetic is done here in Python on purpose: LLMs are unreliable at
counting days, code is not. The agent receives ready-made numbers such as
"days_from_delivery_to_request".
"""

import sqlite3
from datetime import date, timedelta

from refund_agent import config


class ToolError(Exception):
    """Raised when a tool is called with an unknown id. The agent sees the message."""


def _days_between(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def get_refund_request(conn: sqlite3.Connection, request_id: str) -> dict:
    """The refund request itself: reason, customer message, amount, photo, dates."""
    row = conn.execute("SELECT * FROM refund_requests WHERE id = ?", (request_id,)).fetchone()
    if row is None:
        raise ToolError(f"No refund request with id {request_id!r}.")
    result = dict(row)
    result["photo_attached"] = bool(result["photo_attached"])

    shipment = conn.execute("SELECT delivered_at FROM shipments WHERE order_id = ?", (row["order_id"],)).fetchone()
    delivered_at = shipment["delivered_at"] if shipment else None
    result["days_from_delivery_to_request"] = (
        _days_between(delivered_at, row["submitted_at"]) if delivered_at else None
    )
    return result


def get_order(conn: sqlite3.Connection, order_id: str) -> dict:
    """Order details: items with product flags, earlier refunds and payment disputes for this order."""
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise ToolError(f"No order with id {order_id!r}.")

    items = conn.execute(
        """
        SELECT oi.sku, p.name, p.category, oi.quantity, oi.unit_price,
               p.is_hygiene_sealed, p.is_personalized, p.care_instructions
        FROM order_items oi JOIN products p ON p.sku = oi.sku
        WHERE oi.order_id = ?
        """,
        (order_id,),
    ).fetchall()

    earlier_refunds = conn.execute(
        """
        SELECT id, submitted_at, reason, status FROM refund_requests
        WHERE order_id = ? AND status != 'open'
        ORDER BY submitted_at
        """,
        (order_id,),
    ).fetchall()

    disputes = conn.execute(
        "SELECT id, provider, opened_at, status FROM payment_disputes WHERE order_id = ?",
        (order_id,),
    ).fetchall()

    return {
        **dict(order),
        "items": [
            {**dict(i), "is_hygiene_sealed": bool(i["is_hygiene_sealed"]), "is_personalized": bool(i["is_personalized"])}
            for i in items
        ],
        "earlier_refund_requests_for_this_order": [dict(r) for r in earlier_refunds],
        "payment_disputes": [dict(d) for d in disputes],
    }


def get_shipment(conn: sqlite3.Connection, order_id: str) -> dict:
    """Shipping and tracking information, incl. how many days the parcel is overdue."""
    row = conn.execute("SELECT * FROM shipments WHERE order_id = ?", (order_id,)).fetchone()
    if row is None:
        raise ToolError(f"No shipment for order {order_id!r}.")
    result = dict(row)
    today = config.AS_OF_DATE.isoformat()
    result["today"] = today
    result["days_past_expected_delivery"] = (
        max(0, _days_between(row["expected_delivery"], today)) if row["status"] != "delivered" else None
    )
    return result


def get_customer_history(conn: sqlite3.Connection, customer_id: str, current_request_id: str) -> dict:
    """Earlier refund requests of a customer and the abuse-prevention counters from §10."""
    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if customer is None:
        raise ToolError(f"No customer with id {customer_id!r}.")

    requests = conn.execute(
        """
        SELECT id, order_id, submitted_at, reason, status, amount_requested
        FROM refund_requests
        WHERE customer_id = ? AND id != ?
        ORDER BY submitted_at DESC
        """,
        (customer_id, current_request_id),
    ).fetchall()

    today = config.AS_OF_DATE
    last_90_days = (today - timedelta(days=90)).isoformat()
    last_12_months = (today - timedelta(days=365)).isoformat()

    order_count = conn.execute("SELECT COUNT(*) FROM orders WHERE customer_id = ?", (customer_id,)).fetchone()[0]

    return {
        "customer_id": customer["id"],
        "name": customer["name"],
        "customer_since": customer["signup_date"],
        "total_orders": order_count,
        "other_refund_requests": [dict(r) for r in requests],
        "other_refund_requests_last_90_days": sum(r["submitted_at"] >= last_90_days for r in requests),
        "not_received_claims_last_12_months": sum(
            r["reason"] == "not_received" and r["submitted_at"] >= last_12_months for r in requests
        ),
    }


# --- Tool descriptions for Claude --------------------------------------------
# Claude only sees these names, descriptions and input schemas. Good
# descriptions are the most important part of tool design: they tell the model
# WHEN to use a tool, not only what it does.

DATABASE_TOOL_SCHEMAS = [
    {
        "name": "get_refund_request",
        "description": "Load a refund request by its id (e.g. 'R-1001'). Returns reason, customer message, "
                       "requested amount, whether a photo is attached, order_id, customer_id and "
                       "days_from_delivery_to_request. Always call this first.",
        "input_schema": {
            "type": "object",
            "properties": {"request_id": {"type": "string", "description": "Refund request id, e.g. 'R-1001'"}},
            "required": ["request_id"],
        },
    },
    {
        "name": "get_order",
        "description": "Load an order by id: ordered items (with is_hygiene_sealed, is_personalized and care "
                       "instructions), earlier refund requests for the same order and open payment disputes "
                       "(chargebacks).",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "Order id, e.g. 'O-5001'"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "get_shipment",
        "description": "Load shipping and tracking data for an order: status (in_transit, delivered, lost), "
                       "expected and actual delivery date and days_past_expected_delivery. Use for "
                       "'not received' and transport damage cases.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "get_customer_history",
        "description": "Load the customer's other refund requests and the abuse-prevention counters "
                       "(other_refund_requests_last_90_days, not_received_claims_last_12_months).",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "current_request_id": {"type": "string", "description": "The request under review (excluded from counts)"},
            },
            "required": ["customer_id", "current_request_id"],
        },
    },
]

DATABASE_TOOLS = {
    "get_refund_request": get_refund_request,
    "get_order": get_order,
    "get_shipment": get_shipment,
    "get_customer_history": get_customer_history,
}
