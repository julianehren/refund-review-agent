-- Database schema for the fictional online shop "HomeCraft Kitchen".
-- SQLite stores dates as ISO text (YYYY-MM-DD), which sorts and compares correctly.

PRAGMA foreign_keys = ON;

CREATE TABLE customers (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    signup_date TEXT NOT NULL
);

CREATE TABLE products (
    sku               TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    category          TEXT NOT NULL,
    price             REAL NOT NULL CHECK (price > 0),
    is_hygiene_sealed INTEGER NOT NULL DEFAULT 0 CHECK (is_hygiene_sealed IN (0, 1)),
    is_personalized   INTEGER NOT NULL DEFAULT 0 CHECK (is_personalized IN (0, 1)),
    care_instructions TEXT
);

CREATE TABLE orders (
    id             TEXT PRIMARY KEY,
    customer_id    TEXT NOT NULL REFERENCES customers(id),
    order_date     TEXT NOT NULL,
    total_amount   REAL NOT NULL CHECK (total_amount >= 0),
    payment_method TEXT NOT NULL CHECK (payment_method IN ('credit_card', 'paypal', 'invoice'))
);

CREATE TABLE order_items (
    order_id   TEXT NOT NULL REFERENCES orders(id),
    sku        TEXT NOT NULL REFERENCES products(sku),
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL CHECK (unit_price > 0),
    PRIMARY KEY (order_id, sku)
);

CREATE TABLE shipments (
    order_id          TEXT PRIMARY KEY REFERENCES orders(id),
    carrier           TEXT NOT NULL,
    tracking_number   TEXT NOT NULL,
    shipped_at        TEXT NOT NULL,
    expected_delivery TEXT NOT NULL,
    delivered_at      TEXT,  -- NULL while the parcel has not been delivered
    status            TEXT NOT NULL CHECK (status IN ('in_transit', 'delivered', 'lost')),
    -- "delivered" must have a delivery date, the other states must not
    CHECK ((status = 'delivered') = (delivered_at IS NOT NULL))
);

CREATE TABLE refund_requests (
    id               TEXT PRIMARY KEY,
    order_id         TEXT NOT NULL REFERENCES orders(id),
    customer_id      TEXT NOT NULL REFERENCES customers(id),
    submitted_at     TEXT NOT NULL,
    reason           TEXT NOT NULL CHECK (reason IN
                        ('changed_mind', 'damaged_in_transit', 'defective', 'not_received', 'wrong_item')),
    customer_message TEXT NOT NULL,
    amount_requested REAL NOT NULL CHECK (amount_requested > 0),
    photo_attached   INTEGER NOT NULL DEFAULT 0 CHECK (photo_attached IN (0, 1)),
    status           TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'refunded', 'rejected', 'escalated'))
);

CREATE TABLE payment_disputes (
    id        TEXT PRIMARY KEY,
    order_id  TEXT NOT NULL REFERENCES orders(id),
    provider  TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    status    TEXT NOT NULL CHECK (status IN ('open', 'won', 'lost'))
);

-- Audit log of the human-in-the-loop step: what the agent suggested and what the human decided.
CREATE TABLE review_decisions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id     TEXT NOT NULL REFERENCES refund_requests(id),
    agent_decision TEXT NOT NULL CHECK (agent_decision IN ('APPROVE', 'REJECT', 'ESCALATE')),
    human_decision TEXT NOT NULL CHECK (human_decision IN ('APPROVE', 'REJECT', 'ESCALATE')),
    reviewer_note  TEXT,
    model          TEXT,
    cost_usd       REAL,
    decided_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_refund_requests_customer ON refund_requests(customer_id);
CREATE INDEX idx_orders_customer ON orders(customer_id);
