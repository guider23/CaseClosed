from datetime import datetime
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from .db import Dispute, Order, Shipment, ChatLog, Customer


def extract_features(dispute: Dispute, session: Session) -> dict:
    """Single-dispute feature extraction; delegates to the batch path."""
    rows, _ = _build_rows([dispute], session)
    return rows[0]


def build_feature_matrix(disputes, session: Session, expected_columns=None):
    """Build feature matrix + labels for training/eval.

    Loads all required data in 6 fixed queries regardless of dataset size,
    so this stays fast against remote Postgres (no N+1 round trips).
    If expected_columns provided, ensures output matches those columns exactly.
    """
    rows, labels = _build_rows(disputes, session)

    df = pd.DataFrame(rows)
    df = pd.get_dummies(df, columns=["dispute_type", "delivery_status_final"], drop_first=False)

    for col in df.columns:
        if df[col].dtype == bool:
            df[col] = df[col].astype(int)

    if expected_columns is not None:
        for col in expected_columns:
            if col not in df.columns:
                df[col] = 0
        df = df[expected_columns]

    return df.values, np.array(labels)


def _build_rows(disputes, session: Session):
    """Batch-load all related data and compute feature dicts for every dispute."""
    dispute_ids = [d.dispute_id for d in disputes]
    order_ids = [d.order_id for d in disputes]
    payment_ids = [d.payment_id for d in disputes]

    # 6 queries, fixed cost regardless of dataset size
    orders = {
        o.order_id: o
        for o in session.query(Order).filter(Order.order_id.in_(order_ids)).all()
    }
    shipments = {
        s.order_id: s
        for s in session.query(Shipment).filter(Shipment.order_id.in_(order_ids)).all()
    }
    customer_ids = {o.customer_id for o in orders.values()}
    customers = {
        c.customer_id: c
        for c in session.query(Customer).filter(Customer.customer_id.in_(customer_ids)).all()
    }
    chat_logs = {
        c.order_id: c
        for c in session.query(ChatLog).filter(ChatLog.order_id.in_(order_ids)).all()
    }

    # prior disputes per customer: one query, group in Python
    all_customer_payment_ids = (
        session.query(Order.payment_id, Order.customer_id)
        .filter(Order.customer_id.in_(customer_ids))
        .all()
    )
    payment_to_customer = {row.payment_id: row.customer_id for row in all_customer_payment_ids}

    disputed_payment_ids = set(payment_ids)
    prior_dispute_counts: dict[str, int] = {cid: 0 for cid in customer_ids}
    for d_pay in (
        session.query(Dispute.payment_id)
        .filter(Dispute.dispute_id.notin_(dispute_ids))
        .all()
    ):
        cid = payment_to_customer.get(d_pay.payment_id)
        if cid and cid in prior_dispute_counts:
            prior_dispute_counts[cid] += 1

    rows = []
    labels = []
    for dispute in disputes:
        f = {
            "dispute_type": dispute.dispute_type,
            "amount_log": np.log1p(dispute.amount),
            "pod_present": False,
            "delivery_status_final": "unknown",
            "signature_flag": False,
            "customer_account_age_days": 0,
            "customer_prior_disputes": 0,
            "chat_receipt_confirmed": False,
            "chat_thread_exists": False,
            "days_delivery_to_dispute": -1,
        }

        order = orders.get(dispute.order_id)
        if not order:
            rows.append(f)
            labels.append(1 if dispute.label == "merchant_won" else 0)
            continue

        shipment = shipments.get(order.order_id)
        if shipment:
            f["pod_present"] = shipment.pod_id is not None
            f["signature_flag"] = shipment.signature_flag
            if shipment.timeline:
                f["delivery_status_final"] = shipment.timeline[-1].get("status", "unknown")
            if shipment.delivered_at:
                f["days_delivery_to_dispute"] = (dispute.raised_at - shipment.delivered_at).days

        customer = customers.get(order.customer_id)
        if customer:
            f["customer_account_age_days"] = customer.account_age_days
            f["customer_prior_disputes"] = prior_dispute_counts.get(customer.customer_id, 0)

        chat_log = chat_logs.get(order.order_id)
        if chat_log and chat_log.messages:
            f["chat_thread_exists"] = True
            for msg in chat_log.messages:
                if msg["from"] == "customer":
                    text_lower = msg["text"].lower()
                    if any(phrase in text_lower for phrase in ["got it", "received", "arrived"]):
                        f["chat_receipt_confirmed"] = True
                        break

        rows.append(f)
        labels.append(1 if dispute.label == "merchant_won" else 0)

    return rows, labels
