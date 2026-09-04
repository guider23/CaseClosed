# Razorpay API Alignment Specification

This document proves that the backend architecture maps exactly to the official [Razorpay Disputes API](https://razorpay.com/docs/api/disputes/?preferred-country=IN).

## 1. Fetching a Dispute (`GET /v1/disputes/:id`)

When Razorpay emits a webhook or when we fetch a dispute, the JSON schema exactly matches the official documentation:

```json
{
  "id": "disp_AHfqOvkldwsbqt",
  "entity": "dispute",
  "amount": 5000,
  "currency": "INR",
  "status": "open",
  "phase": "chargeback",
  "reason_code": "fraud",
  "reason_description": "Cardholder claims they did not authorize the transaction.",
  "respond_by": 1735689600,
  "created_at": 1704067200,
  "evidence": {}
}
```
*Note: We mock this response structure perfectly in `razorpay_client.py` for demo dispute IDs.*

## 2. Contesting a Dispute (`PATCH /v1/disputes/:id/contest`)

To auto-contest a dispute, Razorpay strictly requires an `amount`, a `summary` of **maximum 1000 characters**, and at least one document ID uploaded via the Documents API. 

Our system dynamically builds this exact required payload:

```json
{
  "amount": 5000,
  "summary": "Delivery confirmed via tracking #12345. Customer accessed digital goods on 2024-01-01. Please reverse this chargeback.",
  "shipping_proof": ["doc_demo_shipping_123"],
  "action": "submit"
}
```

- **LLM Constraint:** Our `LLMComposer` prompt is explicitly instructed to write a `<1000` character summary (not a long letter).
- **Evidence Mapping:** In `api.py`, our `map_evidence_to_docs()` function demonstrates mapping our internal `evidence_bundle` into Document IDs just as would be done in production.
