import hmac
import hashlib
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from .config import config
from .db import Dispute, engine
from .audit import log_audit


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    expected = hmac.new(
        config.razorpay_webhook_secret.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def ingest_dispute(payload: dict, session: Session) -> Dispute | None:
    """Returns None if duplicate, otherwise persists and returns new dispute."""

    # Razorpay webhook structure (verified from docs):
    # payload.dispute.entity contains all dispute fields
    entity = payload.get("payload", {}).get("dispute", {}).get("entity", {})

    dispute_id = entity.get("id")

    if not dispute_id:
        raise ValueError(f"missing dispute id in payload.dispute.entity")

    existing = session.query(Dispute).filter_by(dispute_id=dispute_id).first()
    if existing:
        return None

    # check if order exists for this payment
    from .db import Order
    payment_id = entity.get("payment_id")
    order = session.query(Order).filter_by(payment_id=payment_id).first()

    # if order doesn't exist, save dispute with unmatched status and skip processing
    if not order:
        dispute = Dispute(
            dispute_id=dispute_id,
            payment_id=payment_id,
            order_id=payment_id,  # temporary placeholder to satisfy NOT NULL
            dispute_type=entity.get("reason_code", "item_not_received"),
            reason_code=entity.get("reason_code", ""),
            raised_at=datetime.fromtimestamp(entity.get("created_at", 0)),
            respond_by=datetime.fromtimestamp(entity.get("respond_by", 0)) if entity.get("respond_by") else datetime.utcnow() + timedelta(days=7),
            amount=entity.get("amount", 0) / 100.0,
            currency=entity.get("currency", "INR"),
            label=None,
            split=None,
            status="unmatched_order",
            win_prob=None,
            draft=None,
            gate_reason="payment not found in system",
            evidence_bundle=None
        )
        session.add(dispute)
        session.commit()

        log_audit(
            dispute_id=dispute_id,
            action="received",
            detail=f"unmatched payment_id={payment_id}"
        )
        return dispute

    # order exists, create dispute normally
    dispute = Dispute(
        dispute_id=dispute_id,
        payment_id=payment_id,
        order_id=order.order_id,
        dispute_type=entity.get("reason_code", "item_not_received"),
        reason_code=entity.get("reason_code", ""),
        raised_at=datetime.fromtimestamp(entity.get("created_at", 0)),
        respond_by=datetime.fromtimestamp(entity.get("respond_by", 0)) if entity.get("respond_by") else datetime.utcnow() + timedelta(days=7),
        amount=entity.get("amount", 0) / 100.0,
        currency=entity.get("currency", "INR"),
        label=None,
        split=None,
        status="received",
        win_prob=None,
        draft=None,
        gate_reason=None,
        evidence_bundle=None
    )

    session.add(dispute)
    session.commit()

    log_audit(
        dispute_id=dispute_id,
        action="received",
        detail=f"payment_id={dispute.payment_id}, type={dispute.dispute_type}"
    )

    return dispute
