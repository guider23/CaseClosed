#!/usr/bin/env python3
import sys
import json
import hmac
import hashlib
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from chargeback.config import config
from chargeback.db import Dispute, engine
from sqlalchemy.orm import Session


def sign_payload(body: bytes) -> str:
    return hmac.new(
        config.razorpay_webhook_secret.encode(),
        body,
        hashlib.sha256
    ).hexdigest()


import time
import uuid

def fire_one_dispute(dispute: Dispute, endpoint: str):
    now_ts = int(time.time())
    new_dispute_id = f"disp_demo_{uuid.uuid4().hex[:6]}"
    
    payload = {
        "event": "payment.dispute.created",
        "payload": {
            "dispute": {
                "entity": {
                    "id": new_dispute_id,
                    "payment_id": dispute.payment_id,
                    "amount": int(dispute.amount * 100),  # INR to paise
                    "currency": dispute.currency,
                    "reason_code": dispute.reason_code,
                    "created_at": now_ts,
                    "respond_by": now_ts + (7 * 86400)
                }
            }
        }
    }

    body = json.dumps(payload).encode()
    signature = sign_payload(body)

    headers = {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": signature
    }

    response = requests.post(endpoint, data=body, headers=headers, timeout=10)

    print(f"Fired {dispute.dispute_id}: {response.status_code}")
    return response


if __name__ == "__main__":
    endpoint = f"http://127.0.0.1:{config.port}/webhooks/razorpay"

    if len(sys.argv) > 1 and sys.argv[1] == "--ngrok":
        endpoint = f"https://{config.ngrok_expose_url}"

    print(f"Firing synthetic disputes to {endpoint}")

    with Session(engine) as session:
        disputes = session.query(Dispute).filter_by(split="train").limit(5).all()

        for dispute in disputes:
            fire_one_dispute(dispute, endpoint)
