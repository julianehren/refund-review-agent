"""Create the synthetic shop database with 24 labelled refund cases.

Run:  python -m refund_agent.seed

Each case is designed to test one rule of the store policy (data/store_policy.md).
The correct answer ("label") of every case is written to evals/labels.json –
NOT into the database. The agent only sees the database, so it cannot cheat.
"""

import json
from dataclasses import dataclass, field
from datetime import timedelta

from refund_agent import config, db

AS_OF = config.AS_OF_DATE

PRODUCTS = [
    # sku, name, category, price, hygiene_sealed, personalized, care instructions
    ("P-SKILLET", "Cast Iron Skillet 28 cm", "Cookware", 49.90, 0, 0, "Hand wash only. Never put in the dishwasher."),
    ("P-KNIVES", "Chef Knife Set (5 pcs)", "Cutlery", 129.00, 0, 0, "Hand wash recommended."),
    ("P-MIXER", "Stand Mixer 1200 W", "Appliances", 349.00, 0, 0, None),
    ("P-BOARD-ENG", "Engraved Oak Cutting Board", "Cutlery", 59.00, 0, 1, "Hand wash only. Oil regularly."),
    ("P-FILTER", "Water Filter Cartridges (3-pack)", "Accessories", 24.90, 1, 0, None),
    ("P-BABYSET", "Silicone Baby Feeding Set", "Accessories", 34.90, 1, 0, "Dishwasher safe."),
    ("P-POTSET", "Stainless Steel Pot Set (4 pcs)", "Cookware", 189.00, 0, 0, "Dishwasher safe."),
    ("P-KETTLE", "Electric Kettle 1.7 L", "Appliances", 39.90, 0, 0, None),
    ("P-SPICES", "Spice Jar Set (12 pcs)", "Accessories", 29.90, 0, 0, "Dishwasher safe."),
    ("P-DUTCH", "Enameled Dutch Oven 5 L", "Cookware", 119.00, 0, 0, "Hand wash recommended."),
]
PRICES = {p[0]: p[3] for p in PRODUCTS}


def day(days_ago: int) -> str:
    """ISO date string for 'n days before the simulation date'."""
    return (AS_OF - timedelta(days=days_ago)).isoformat()


@dataclass
class Case:
    """One open refund request plus everything needed to create it."""

    id: str
    customer: str
    sku: str
    reason: str
    message: str
    expected: str              # APPROVE / REJECT / ESCALATE – the label
    policy: str                # the policy section that decides the case
    delivered_days_before: int | None = 3   # None = never delivered
    shipment_status: str = "delivered"
    days_past_expected: int = 0             # only for parcels that never arrived
    photo: bool = False
    submitted_days_ago: int = 1
    order_sku_differs: str | None = None    # for "wrong item": what was actually ordered
    history: list[dict] = field(default_factory=list)  # earlier refund requests of this customer
    open_dispute: bool = False
    already_refunded: bool = False


CASES = [
    Case("R-1001", "Anna Weber", "P-KETTLE", "changed_mind",
         "Hi, the kettle is fine but I found one that matches my kitchen better. It's unused and still in the box.",
         "APPROVE", "§2", delivered_days_before=6,
         history=[{"days_ago": 200, "reason": "changed_mind", "status": "refunded"}]),
    Case("R-1002", "Lukas Becker", "P-SPICES", "changed_mind",
         "I'd like to return the spice jars, I don't need them anymore. Never opened.",
         "REJECT", "§3", delivered_days_before=21),
    Case("R-1003", "Sophie Klein", "P-SKILLET", "damaged_in_transit",
         "The skillet arrived with a big crack in the handle, the box was crushed. Photo attached.",
         "APPROVE", "§5", delivered_days_before=2, photo=True),
    Case("R-1004", "Jonas Wolf", "P-DUTCH", "damaged_in_transit",
         "The enamel of the dutch oven is chipped, I think it happened during shipping.",
         "ESCALATE", "§5", delivered_days_before=3, photo=False),
    Case("R-1005", "Mia Schröder", "P-KNIVES", "not_received",
         "My knife set never arrived. Tracking hasn't changed in two weeks.",
         "APPROVE", "§6", delivered_days_before=None, shipment_status="lost", days_past_expected=14),
    Case("R-1006", "Felix Neumann", "P-POTSET", "not_received",
         "I never got my pot set, but the tracking says delivered. There was nothing at my door.",
         "ESCALATE", "§6", delivered_days_before=5),
    Case("R-1007", "Laura Schwarz", "P-KETTLE", "defective",
         "The kettle stopped heating up completely. I've had it for about 8 months.",
         "APPROVE", "§4", delivered_days_before=240),
    Case("R-1008", "Paul Zimmermann", "P-POTSET", "defective",
         "The bottom of the large pot has warped and it doesn't sit flat on the stove anymore.",
         "REJECT", "§4", delivered_days_before=900),
    Case("R-1009", "Emma Braun", "P-FILTER", "changed_mind",
         "I opened the filter pack but realised they don't fit my jug. Can I return them?",
         "REJECT", "§8", delivered_days_before=5),
    Case("R-1010", "Leon Hofmann", "P-BOARD-ENG", "changed_mind",
         "I ordered the engraved board as a gift but the wedding was cancelled. Please refund.",
         "REJECT", "§8", delivered_days_before=4),
    Case("R-1011", "Hannah Krüger", "P-BOARD-ENG", "damaged_in_transit",
         "The engraved board arrived split in two pieces. Photo of the board and the packaging attached.",
         "APPROVE", "§5", delivered_days_before=1, photo=True),
    Case("R-1012", "Noah Hartmann", "P-SPICES", "wrong_item",
         "I ordered the chef knife set but received a spice jar set instead.",
         "APPROVE", "§7", delivered_days_before=2, order_sku_differs="P-KNIVES"),
    Case("R-1013", "Lena Lange", "P-MIXER", "defective",
         "The stand mixer makes a loud grinding noise and the bowl doesn't turn anymore.",
         "ESCALATE", "§9", delivered_days_before=60),
    Case("R-1014", "Ben Schmitt", "P-KETTLE", "changed_mind",
         "Don't need the kettle anymore, unused, please refund.",
         "ESCALATE", "§10", delivered_days_before=4,
         history=[{"days_ago": 20, "reason": "changed_mind", "status": "refunded"},
                  {"days_ago": 45, "reason": "damaged_in_transit", "status": "refunded"},
                  {"days_ago": 70, "reason": "changed_mind", "status": "refunded"}]),
    Case("R-1015", "Clara Werner", "P-DUTCH", "not_received",
         "The dutch oven never arrived and tracking shows it as lost.",
         "ESCALATE", "§10", delivered_days_before=None, shipment_status="lost", days_past_expected=12,
         history=[{"days_ago": 120, "reason": "not_received", "status": "refunded"},
                  {"days_ago": 250, "reason": "not_received", "status": "refunded"}]),
    Case("R-1016", "Elias Krause", "P-KNIVES", "defective",
         "Two of the knives have rust spots after a few weeks. I also contacted my credit card company.",
         "ESCALATE", "§11", delivered_days_before=30, open_dispute=True),
    Case("R-1017", "Marie Meier", "P-SKILLET", "damaged_in_transit",
         "Following up on my damaged skillet – I still want my money back!",
         "REJECT", "§12", delivered_days_before=9, photo=True, already_refunded=True),
    Case("R-1018", "Finn Koch", "P-SPICES", "changed_mind",
         "Changed my mind about the spice jars, they're still sealed in the original packaging.",
         "APPROVE", "§2", delivered_days_before=14),
    Case("R-1019", "Lina Richter", "P-KETTLE", "changed_mind",
         "I'd like to send the kettle back, it's unused.",
         "REJECT", "§3", delivered_days_before=15),
    Case("R-1020", "Tim Bauer", "P-DUTCH", "damaged_in_transit",
         "Just unpacked the dutch oven after coming back from holiday – the lid is cracked. Photo attached.",
         "ESCALATE", "§5", delivered_days_before=10, photo=True),
    Case("R-1021", "Ella Fischer", "P-KNIVES", "changed_mind",
         "The knives are too heavy for me. Unused, original packaging.",
         "APPROVE", "§2", delivered_days_before=6,
         history=[{"days_ago": 30, "reason": "wrong_item", "status": "refunded"},
                  {"days_ago": 80, "reason": "changed_mind", "status": "refunded"}]),
    Case("R-1022", "Max Schulz", "P-SKILLET", "defective",
         "The skillet is completely rusty after I washed it in the dishwasher a couple of times. Poor quality!",
         "REJECT", "§4", delivered_days_before=120),
    Case("R-1023", "Nora Vogel", "P-POTSET", "changed_mind",
         "I used the pots a few times but I don't really like them. Please refund.",
         "REJECT", "§2", delivered_days_before=8),
    Case("R-1024", "David Keller", "P-BABYSET", "not_received",
         "Where is my order? It should have arrived by now.",
         "REJECT", "§6", delivered_days_before=None, shipment_status="in_transit", days_past_expected=3),
]


def build_database(db_path=None) -> None:
    """(Re)create the database file and fill it with products, customers, orders and requests."""
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    conn = db.connect(path)
    db.create_schema(conn)
    conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", PRODUCTS)

    order_no = 5000
    for n, case in enumerate(CASES, start=1):
        customer_id = f"C-{n:03d}"
        email = case.customer.lower().replace(" ", ".").replace("ö", "oe").replace("ü", "ue") + "@example.com"
        conn.execute("INSERT INTO customers VALUES (?, ?, ?, ?)",
                     (customer_id, case.customer, email, day(400 + n * 7)))

        # Earlier refund requests (history) – each on its own small order
        for k, h in enumerate(case.history, start=1):
            order_no += 1
            old_order = f"O-{order_no}"
            _insert_order(conn, old_order, customer_id, "P-SPICES", h["days_ago"] + 5, delivered_days_ago=h["days_ago"] + 2)
            conn.execute(
                "INSERT INTO refund_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"{case.id}-H{k}", old_order, customer_id, day(h["days_ago"]), h["reason"],
                 "(historic request)", PRICES["P-SPICES"], 0, h["status"]))

        # The order this refund request is about
        order_no += 1
        order_id = f"O-{order_no}"
        ordered_sku = case.order_sku_differs or case.sku
        submitted = case.submitted_days_ago
        if case.delivered_days_before is not None:
            delivered_ago = submitted + case.delivered_days_before
            _insert_order(conn, order_id, customer_id, ordered_sku, delivered_ago + 3, delivered_days_ago=delivered_ago)
        else:
            expected_ago = submitted + case.days_past_expected
            _insert_order(conn, order_id, customer_id, ordered_sku, expected_ago + 3,
                          delivered_days_ago=None, expected_days_ago=expected_ago, status=case.shipment_status)

        if case.already_refunded:
            conn.execute(
                "INSERT INTO refund_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"{case.id}-H0", order_id, customer_id, day(submitted + 6), case.reason,
                 "(earlier request for the same order)", PRICES[ordered_sku], 1, "refunded"))
        if case.open_dispute:
            conn.execute("INSERT INTO payment_disputes VALUES (?, ?, ?, ?, ?)",
                         (f"D-{order_no}", order_id, "Credit card (Visa)", day(submitted + 2), "open"))

        conn.execute(
            "INSERT INTO refund_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case.id, order_id, customer_id, day(submitted), case.reason, case.message,
             PRICES[ordered_sku], int(case.photo), "open"))

    conn.commit()
    conn.close()


def _insert_order(conn, order_id, customer_id, sku, ordered_days_ago, delivered_days_ago,
                  expected_days_ago=None, status="delivered") -> None:
    """Insert an order with one item and its shipment."""
    price = PRICES[sku]
    payment = ["credit_card", "paypal", "invoice"][int(order_id[2:]) % 3]
    conn.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?)",
                 (order_id, customer_id, day(ordered_days_ago), price, payment))
    conn.execute("INSERT INTO order_items VALUES (?, ?, ?, ?)", (order_id, sku, 1, price))
    shipped = ordered_days_ago - 1
    if delivered_days_ago is not None:
        expected = delivered_days_ago
    else:
        expected = expected_days_ago
    conn.execute(
        "INSERT INTO shipments VALUES (?, ?, ?, ?, ?, ?, ?)",
        (order_id, "DHL", f"JJD{order_id[2:]}00{len(customer_id)}", day(shipped), day(expected),
         day(delivered_days_ago) if delivered_days_ago is not None else None, status))


def write_labels() -> None:
    """Write the expected decision of every case to evals/labels.json."""
    labels = {c.id: {"expected": c.expected, "policy": c.policy} for c in CASES}
    config.LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.LABELS_PATH.write_text(json.dumps(labels, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build_database()
    write_labels()
    print(f"Database created at {config.DB_PATH} with {len(CASES)} open refund requests.")
    print(f"Labels written to {config.LABELS_PATH}.")
