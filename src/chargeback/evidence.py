from datetime import datetime
from sqlalchemy.orm import Session
from .db import Dispute, Order, Shipment, ChatLog, Customer


def build_evidence_bundle(dispute: Dispute, session: Session) -> dict:
    """Extract verified facts only. Missing facts are absent, never null-filled."""
    bundle = {}

    order = session.query(Order).filter_by(order_id=dispute.order_id).first()
    if not order:
        return bundle

    bundle["order.id"] = order.order_id
    bundle["order.amount"] = order.amount
    bundle["order.date"] = order.order_date.isoformat()
    bundle["order.item"] = order.item

    shipment = session.query(Shipment).filter_by(order_id=order.order_id).first()
    if shipment:
        bundle["shipment.courier"] = shipment.courier
        bundle["shipment.tracking_id"] = shipment.tracking_id

        if shipment.delivered_at:
            bundle["shipment.delivered_at"] = shipment.delivered_at.isoformat()
        if shipment.pod_id:
            bundle["shipment.pod_id"] = shipment.pod_id
        if shipment.receiver_name:
            bundle["shipment.receiver"] = shipment.receiver_name
        if shipment.signature_flag:
            bundle["shipment.signature"] = True

        final_status = None
        if shipment.timeline:
            final_status = shipment.timeline[-1].get("status")
        if final_status:
            bundle["shipment.status_final"] = final_status

    customer = session.query(Customer).filter_by(customer_id=order.customer_id).first()
    if customer:
        bundle["customer.account_age_days"] = customer.account_age_days

        prior_disputes = session.query(Dispute).filter(
            Dispute.order_id != dispute.order_id,
            Dispute.payment_id.in_(
                session.query(Order.payment_id).filter_by(customer_id=customer.customer_id)
            )
        ).count()
        bundle["customer.prior_disputes"] = prior_disputes

    chat_log = session.query(ChatLog).filter_by(order_id=order.order_id).first()
    if chat_log and chat_log.messages:
        bundle["chat.thread_exists"] = True

        # simple regex for receipt confirmation
        for msg in chat_log.messages:
            if msg["from"] == "customer":
                text_lower = msg["text"].lower()
                if any(phrase in text_lower for phrase in ["got it", "received", "arrived"]):
                    bundle["chat.receipt_confirmed"] = True
                    bundle["chat.receipt_excerpt"] = msg["text"]
                    bundle["chat.receipt_ts"] = msg["ts"]
                    break

    return bundle
