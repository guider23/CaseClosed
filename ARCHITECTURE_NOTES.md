# ARCHITECTURE_NOTES.md - CaseClosed - Binding Technical Specification

Product name: CaseClosed. Tagline: "AI chargeback defense with evidence you
can audit". Use this name in all user-facing surfaces (dashboard header,
README, docs).

This document is the source of truth for HOW the system works. CLAUDE.md
defines behavior and process; this file defines design. Do not deviate.

## 1. End-to-end flow

```
Razorpay webhook (or synthetic sender) -> POST /webhooks/razorpay
  -> verify HMAC signature -> persist dispute -> build evidence bundle
  -> classifier: win probability -> gate
       -> AUTO path: LLM composer -> citation validator -> draft stored
       -> HUMAN path: review queue with reason
  -> dashboard renders queue/detail/stats
  -> "Approve & Submit" -> Razorpay contest client (real test-mode or mock)
  -> every step appends to audit JSONL
```

## 2. Configuration

All from environment via src/chargeback/config.py (pydantic-settings).
See .env.example. Required behavior:

- Real credentials ONLY. NO mocks, NO fallbacks. System connects to:
  - Real LLM API (Gemini/Anthropic/OpenAI from .env)
  - Real Razorpay test-mode API with actual credentials
  - Real database (Postgres from .env)
- Code uses SQLAlchemy so any SQL dialect works by changing DATABASE_URL only.
  Do not write raw database-specific SQL.

## 3. Synthetic data world (generator, deterministic seed=42)

Generate in dependency order:

- customers (~200): customer_id, account_age_days, persona in
  {normal: 85%, abuser: 8%, unlucky: 7%}. Abusers: young accounts, multiple
  disputes. Unlucky: legit customers whose orders genuinely had issues.
- orders (~600): order_id, customer_id, amount (log-normal, INR 300-25000),
  item, order_date, payment_id.
- shipments (1 per order): courier, tracking_id, timeline events
  (picked_up -> in_transit -> delivered) with timestamps, delivered_at,
  pod_id (proof of delivery), receiver_name, signature_flag.
  ~90% complete; ~10% missing pod_id or delivered_at (courier scan gaps).
- chat_logs (for ~60% of orders): templated multi-turn threads with variation.
  Key evidence signal: for a slice of item-not-received disputes from abuser
  personas, include a receipt confirmation line ("got it, thanks") BEFORE the
  dispute date. Timestamps on every message.
- disputes (~120): dispute_id, payment_id, order link, type in
  {item_not_received, unauthorized, not_as_described, duplicate},
  reason_code (mirror Razorpay codes), raised_at, respond_by (raised_at + 7d),
  amount, label merchant_won/merchant_lost.

Label generation = rules + noise (IMPORTANT: keep the noise):

- delivered + POD + chat receipt confirmation -> won ~92%
- delivered + POD, no chat -> won ~75%
- missing POD -> won ~25%
- abuser persona bumps win chance up for merchant, unlucky bumps down
- flip ~7% of labels at random (bank decisions are noisy in reality).
  If the classifier scores near-perfect, the simulation is too easy - do not
  celebrate it, add noise.

80/20 train/held-out split on disputes, stratified by type, written to
data/split.json on first generation and NEVER regenerated afterwards.

## 4. Dispute ingestion (webhooks)

- POST /webhooks/razorpay accepting the real Razorpay payment.dispute.created
  payload shape (entity: dispute with id, payment_id, amount, currency,
  reason_code, status, respond_by). Copy field names from Razorpay docs.
- Verify X-Razorpay-Signature: HMAC-SHA256 of raw body with
  RAZORPAY_WEBHOOK_SECRET. Reject 401 on mismatch. TESTED both ways.
- The generator doubles as webhook sender: scripts/fire_disputes.py POSTs
  synthetic disputes (correctly signed) to the local endpoint at a chosen
  rate. This is the live-demo mechanism.
- Idempotency: duplicate dispute_id -> 200, no reprocessing.
- NGROK_EXPOSE_URL=augmentable-kathline-diffidently.ngrok-free.dev/webhooks/razorpay

## 5. Classifier (NO LLM in this layer)

Features per dispute:

- dispute_type (one-hot), amount (log), days_delivery_to_dispute,
  pod_present (bool), delivery_status_final, signature_flag,
  customer_account_age_days, customer_prior_disputes, customer_prior_refunds,
  chat_receipt_confirmed (bool - simple regex over chat log for receipt
  phrases, deliberately NOT an LLM call), chat_thread_exists (bool).
  Model: sklearn GradientBoostingClassifier wrapped in CalibratedClassifierCV
  (sigmoid). Train on train split only. Report on frozen held-out only.
  Threshold: sweep on TRAIN split minimizing expected cost:
  cost = FP * FP_COST_INR + FN * mean_dispute_amount
  where FP_COST_INR is configurable (default 2000 - proxy for lost goodwill
  of a wrongly auto-fought good customer). Chosen threshold + the sweep table
  go in METRICS.md.

## 6. Evidence bundle, LLM composer, citation validator

Evidence bundle = flat JSON of VERIFIED facts only, namespaced keys:
  order.amount, order.date, shipment.delivered_at, shipment.pod_id,
  shipment.receiver, chat.receipt_excerpt, chat.receipt_ts,
  customer.account_age_days, customer.prior_disputes ... Missing facts are
  ABSENT from the bundle, never null-filled with guesses.

Composer (src/chargeback/compose.py):

- Interface: Composer.compose(bundle, dispute) -> DraftResponse.
- LLMComposer uses LLM_PROVIDER/LLM_MODEL from env via a thin client
  (anthropic, openai, or gemini SDK, selected by provider string). Temperature 0.
- System prompt requirements (write it verbatim in code, not paraphrased):
  formal chargeback rebuttal; ONLY facts present in the JSON bundle; every
  sentence ends with [source: <key>, ...]; fixed structure: intro,
  delivery evidence, customer-behavior evidence, conclusion requesting
  reversal; if a needed fact is absent, omit the point entirely; never
  speculate; never mention the customer abusively.
- On LLM timeout/error: retry once with exponential backoff. Second failure
  -> route to human review with reason "composer_failed". NO template fallback.

Validator (src/chargeback/validate.py) - plain Python, no AI:

- Parse every [source: ...] tag; every key must exist in the bundle.
- Sentence without a tag -> fail. Tag with unknown key -> fail.
- Value spot-check: if cited key's value is a date or ID, that value string
  must appear in the sentence.
- On fail: reject draft, regenerate ONCE with failure reasons appended to the
  prompt. Second fail -> route dispute to human review with reason
  "composer_validation_failed". This path is the failure-recovery demo.

## 7. Gate and dashboard

Gate: human review iff win_prob < threshold OR critical evidence missing
(pod_id absent for item_not_received; payment metadata absent for
unauthorized) OR validator failed twice. Reason string always recorded.

Dashboard: FastAPI serves JSON (/disputes, /disputes/{id}, /stats,
POST /disputes/{id}/approve, POST /disputes/{id}/escalate) + one static
HTML/JS page (CDN Vue or vanilla, NO build toolchain, NO npm).
Views:

1. Queue table: dispute id, type, amount, age, respond-by countdown,
   win-probability badge (green >= threshold+0.15, amber near threshold,
   red below), status chip (auto_responded / human_review / evidence_gap /
   submitted).
2. Detail: evidence checklist (found/missing per expected item for that
   dispute type), the draft with each citation tag rendered as a clickable
   chip that highlights the source field in an evidence side panel,
   confidence score, buttons Approve & Submit / Send to human review.
3. Stats bar: total INR at stake, INR recovered (batch simulation result),
   auto-response rate, held-out precision/recall.
   Clean and fast. No polish theater.

## 8. Audit trail

Append-only logs/audit.jsonl, one line per state change:
{"ts": iso8601, "dispute_id": str, "action": one of [received, scored,
 auto_drafted, draft_rejected, regenerated, gated_human, approved,
 escalated, submitted, submit_failed], "win_prob": float|null,
 "basis": [str], "actor": "system"|"human", "detail": str|null}
Dashboard detail view shows the audit lines for that dispute.

## 9. Failure paths (each one TESTED, several demo-able)

- Webhook bad signature -> 401, logged, not persisted.
- Malformed payload -> 422 with clear error.
- Duplicate dispute -> idempotent 200.
- Missing POD on item_not_received -> evidence_gap status, human queue.
- LLM timeout/error -> retry once -> second fail -> human review, audit-logged.
- Hallucinated citation -> validator reject -> regenerate -> second fail ->
  human queue. (VIDEO MOMENT)


## 10. Razorpay integration

RazorpayClient: fetch_dispute(id), submit_contest(dispute_id, draft,
evidence_refs). Hits test-mode REST API with basic auth (KEY_ID:KEY_SECRET).
Real API only - no mocks.

## 11. Batch recovery simulation (for stats bar + METRICS.md)

Run the full pipeline over the held-out disputes; INR recovered = sum of
amounts for disputes where system chose to contest AND label = merchant_won,
minus FP cost for contested-and-lost. Compare against two baselines:
contest-everything and contest-nothing. Table goes in METRICS.md.
