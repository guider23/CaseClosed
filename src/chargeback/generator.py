import random
import json
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
from chargeback.db import SessionLocal, Customer, Order, Shipment, ChatLog, Dispute, init_db
from chargeback.model import train_and_save

_REPO_ROOT = Path(__file__).parent.parent.parent

SEED = 42
random.seed(SEED)
np.random.seed(SEED)

DISPUTE_TYPES = ["item_not_received", "unauthorized", "not_as_described", "duplicate"]
ITEMS = [
    "wireless_earbuds", "phone_case", "laptop_bag", "usb_cable", "power_bank",
    "smartwatch", "keyboard", "mouse", "webcam", "headphones", "tablet_stand",
    "screen_protector", "charger", "adapter", "memory_card"
]
COURIERS = ["BlueDart", "Delhivery", "EcomExpress", "DTDC"]


def generate_customers(n=200):
    personas = (
        ["normal"] * int(n * 0.85) +
        ["abuser"] * int(n * 0.08) +
        ["unlucky"] * int(n * 0.07)
    )
    random.shuffle(personas)

    customers = []
    for i in range(n):
        persona = personas[i]
        if persona == "abuser":
            age = random.randint(15, 90)
        elif persona == "unlucky":
            age = random.randint(180, 800)
        else:
            age = random.randint(90, 1200)

        customers.append(Customer(
            customer_id=f"cust_{i:04d}",
            account_age_days=age,
            persona=persona
        ))
    return customers


def generate_orders(customers, n=600):
    orders = []
    start_date = datetime.now() - timedelta(days=90)

    for i in range(n):
        customer = random.choice(customers)
        amount = float(np.random.lognormal(7.5, 0.8))
        amount = max(300, min(25000, amount))

        order_date = start_date + timedelta(days=random.randint(0, 80))

        orders.append(Order(
            order_id=f"ord_{i:05d}",
            customer_id=customer.customer_id,
            payment_id=f"pay_{i:05d}",
            amount=round(amount, 2),
            item=random.choice(ITEMS),
            order_date=order_date
        ))
    return orders


def generate_shipments(orders):
    shipments = []
    for order in orders:
        courier = random.choice(COURIERS)
        tracking_id = f"{courier[:3].upper()}{random.randint(100000, 999999)}"

        picked_up = order.order_date + timedelta(hours=random.randint(12, 48))
        in_transit = picked_up + timedelta(hours=random.randint(24, 96))

        # 90% complete delivery, 10% missing pod or delivered_at
        complete = random.random() < 0.9

        if complete:
            delivered = in_transit + timedelta(hours=random.randint(12, 72))
            timeline = [
                {"status": "picked_up", "ts": picked_up.isoformat()},
                {"status": "in_transit", "ts": in_transit.isoformat()},
                {"status": "delivered", "ts": delivered.isoformat()}
            ]
            pod_id = f"POD{random.randint(10000, 99999)}"
            receiver_name = f"Receiver_{random.randint(1, 50)}"
        else:
            delivered = None
            timeline = [
                {"status": "picked_up", "ts": picked_up.isoformat()},
                {"status": "in_transit", "ts": in_transit.isoformat()}
            ]
            pod_id = None
            receiver_name = None

        shipments.append(Shipment(
            order_id=order.order_id,
            courier=courier,
            tracking_id=tracking_id,
            timeline=timeline,
            delivered_at=delivered,
            pod_id=pod_id,
            receiver_name=receiver_name,
            signature_flag=random.random() < 0.7
        ))
    return shipments


def generate_chat_logs(orders, customers_by_id):
    chat_logs = []

    for order in orders:
        if random.random() > 0.6:
            continue

        customer = customers_by_id[order.customer_id]
        msgs = []

        # initial inquiry
        inquiry_time = order.order_date + timedelta(hours=random.randint(48, 120))
        msgs.append({
            "ts": inquiry_time.isoformat(),
            "from": "customer",
            "text": random.choice([
                "where is my order?",
                "tracking shows no updates",
                "expected delivery but nothing arrived",
                "order status please"
            ])
        })

        # support response
        response_time = inquiry_time + timedelta(hours=random.randint(2, 24))
        msgs.append({
            "ts": response_time.isoformat(),
            "from": "support",
            "text": f"Your order {order.order_id} is in transit, expected delivery in 2-3 days."
        })

        # receipt confirmation for some abuser cases
        if customer.persona == "abuser" and random.random() < 0.3:
            receipt_time = response_time + timedelta(days=random.randint(1, 3))
            msgs.append({
                "ts": receipt_time.isoformat(),
                "from": "customer",
                "text": random.choice([
                    "got it, thanks",
                    "received, all good",
                    "order arrived, thank you"
                ])
            })

        chat_logs.append(ChatLog(
            order_id=order.order_id,
            messages=msgs
        ))

    return chat_logs


def generate_disputes(orders, shipments_by_order, customers_by_id, chat_logs_by_order, n=120):
    disputes = []

    # pick orders that are old enough to have disputes
    eligible = [o for o in orders if (datetime.now() - o.order_date).days > 10]
    selected = random.sample(eligible, min(n, len(eligible)))

    for i, order in enumerate(selected):
        dispute_type = random.choice(DISPUTE_TYPES)
        shipment = shipments_by_order[order.order_id]
        customer = customers_by_id[order.customer_id]
        chat_log = chat_logs_by_order.get(order.order_id)

        raised = order.order_date + timedelta(days=random.randint(15, 60))
        respond_by = raised + timedelta(days=7)

        # label generation with noise
        win_score = 0.0

        if shipment.delivered_at and shipment.pod_id:
            win_score += 0.75

            if chat_log:
                receipt_confirmed = any(
                    "got it" in msg["text"].lower() or
                    "received" in msg["text"].lower() or
                    "arrived" in msg["text"].lower()
                    for msg in chat_log.messages if msg["from"] == "customer"
                )
                if receipt_confirmed:
                    win_score += 0.17
        else:
            win_score += 0.25

        if customer.persona == "abuser":
            win_score += 0.08
        elif customer.persona == "unlucky":
            win_score -= 0.10

        # flip 7% at random
        if random.random() < 0.07:
            win_score = 1.0 - win_score

        label = "merchant_won" if random.random() < win_score else "merchant_lost"

        disputes.append(Dispute(
            dispute_id=f"disp_{i:05d}",
            payment_id=order.payment_id,
            order_id=order.order_id,
            dispute_type=dispute_type,
            reason_code=f"{dispute_type}_code",
            raised_at=raised,
            respond_by=respond_by,
            amount=order.amount,
            currency="INR",
            label=label
        ))

    return disputes


def create_split(disputes):
    """80/20 stratified split by type, frozen."""
    split_file = _REPO_ROOT / "data" / "split.json"
    if split_file.exists():
        with open(split_file) as f:
            return json.load(f)

    by_type = {}
    for d in disputes:
        by_type.setdefault(d.dispute_type, []).append(d.dispute_id)

    train_ids = []
    held_out_ids = []

    for dtype, ids in by_type.items():
        random.shuffle(ids)
        split_point = int(len(ids) * 0.8)
        train_ids.extend(ids[:split_point])
        held_out_ids.extend(ids[split_point:])

    split = {"train": train_ids, "held_out": held_out_ids}

    split_file.parent.mkdir(exist_ok=True)
    with open(split_file, "w") as f:
        json.dump(split, f, indent=2)

    return split


def generate_world():
    print("generating synthetic world (seed=42)...")

    init_db()
    session = SessionLocal()

    # clear existing
    session.query(Dispute).delete()
    session.query(ChatLog).delete()
    session.query(Shipment).delete()
    session.query(Order).delete()
    session.query(Customer).delete()
    session.commit()

    customers = generate_customers(200)
    session.bulk_save_objects(customers)
    session.commit()
    print(f"  {len(customers)} customers")

    customers_by_id = {c.customer_id: c for c in customers}

    orders = generate_orders(customers, 600)
    session.bulk_save_objects(orders)
    session.commit()
    print(f"  {len(orders)} orders")

    shipments = generate_shipments(orders)
    session.bulk_save_objects(shipments)
    session.commit()
    print(f"  {len(shipments)} shipments")

    shipments_by_order = {s.order_id: s for s in shipments}

    chat_logs = generate_chat_logs(orders, customers_by_id)
    session.bulk_save_objects(chat_logs)
    session.commit()
    print(f"  {len(chat_logs)} chat logs")

    chat_logs_by_order = {c.order_id: c for c in chat_logs}

    disputes = generate_disputes(orders, shipments_by_order, customers_by_id, chat_logs_by_order, 120)

    split = create_split(disputes)

    for d in disputes:
        if d.dispute_id in split["train"]:
            d.split = "train"
        else:
            d.split = "held_out"

    session.bulk_save_objects(disputes)
    session.commit()
    print(f"  {len(disputes)} disputes ({len(split['train'])} train, {len(split['held_out'])} held-out)")

    session.close()
    print("world generation complete")

    print("training classifier...")
    train_and_save()


if __name__ == "__main__":
    generate_world()
