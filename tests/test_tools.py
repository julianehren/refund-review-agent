"""Tests for the database tools. They check the facts the agent will rely on."""

import json

import pytest

from refund_agent import seed, tools


def test_every_seed_case_has_an_open_request(conn):
    open_ids = {r["id"] for r in conn.execute("SELECT id FROM refund_requests WHERE status = 'open'")}
    assert open_ids == {c.id for c in seed.CASES}


def test_days_from_delivery_to_request_is_calculated(conn):
    request = tools.get_refund_request(conn, "R-1018")
    assert request["days_from_delivery_to_request"] == 14  # edge case: day 14 still counts
    assert request["photo_attached"] is False


def test_request_for_undelivered_parcel_has_no_delivery_days(conn):
    request = tools.get_refund_request(conn, "R-1005")
    assert request["days_from_delivery_to_request"] is None


def test_unknown_request_raises_tool_error(conn):
    with pytest.raises(tools.ToolError):
        tools.get_refund_request(conn, "R-9999")


def test_order_shows_product_flags(conn):
    request = tools.get_refund_request(conn, "R-1009")
    order = tools.get_order(conn, request["order_id"])
    assert order["items"][0]["is_hygiene_sealed"] is True


def test_order_shows_payment_dispute(conn):
    request = tools.get_refund_request(conn, "R-1016")
    order = tools.get_order(conn, request["order_id"])
    assert len(order["payment_disputes"]) == 1


def test_order_shows_earlier_refund_for_same_order(conn):
    request = tools.get_refund_request(conn, "R-1017")
    order = tools.get_order(conn, request["order_id"])
    assert order["earlier_refund_requests_for_this_order"][0]["status"] == "refunded"


def test_wrong_item_case_lists_the_ordered_product(conn):
    request = tools.get_refund_request(conn, "R-1012")
    order = tools.get_order(conn, request["order_id"])
    assert order["items"][0]["sku"] == "P-KNIVES"


def test_lost_parcel_is_overdue(conn):
    request = tools.get_refund_request(conn, "R-1005")
    shipment = tools.get_shipment(conn, request["order_id"])
    assert shipment["status"] == "lost"
    assert shipment["days_past_expected_delivery"] >= 10


def test_abuse_counters(conn):
    r14 = tools.get_refund_request(conn, "R-1014")
    history = tools.get_customer_history(conn, r14["customer_id"], "R-1014")
    assert history["other_refund_requests_last_90_days"] == 3

    r15 = tools.get_refund_request(conn, "R-1015")
    history = tools.get_customer_history(conn, r15["customer_id"], "R-1015")
    assert history["not_received_claims_last_12_months"] == 2

    # R-1021 has 2 requests in 90 days – below the threshold of 3
    r21 = tools.get_refund_request(conn, "R-1021")
    history = tools.get_customer_history(conn, r21["customer_id"], "R-1021")
    assert history["other_refund_requests_last_90_days"] == 2


def test_tool_results_are_json_serialisable(conn):
    request = tools.get_refund_request(conn, "R-1001")
    results = [
        request,
        tools.get_order(conn, request["order_id"]),
        tools.get_shipment(conn, request["order_id"]),
        tools.get_customer_history(conn, request["customer_id"], "R-1001"),
    ]
    for result in results:
        json.dumps(result)  # raises if something cannot be sent to Claude


def test_every_tool_has_a_schema():
    schema_names = {s["name"] for s in tools.DATABASE_TOOL_SCHEMAS}
    assert schema_names == set(tools.DATABASE_TOOLS)
