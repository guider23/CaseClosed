# 5-Minute Demo Script

## 0:00 - 0:30: Introduction
- Briefly introduce **CaseClosed**: An AI-powered chargeback responder that uses Machine Learning (XGBoost) to predict win probability, and an LLM (Gemini 2.5 Flash) to format the rebuttal.
- State the core thesis: "LLMs are bad at statistics but great at formatting. We use classical ML to decide *if* we should fight, and an LLM to decide *how* to fight, guarded by a deterministic Python validator."

## 0:30 - 1:30: The Dashboard & The Happy Path
- Open the terminal and run `make run` to boot the server.
- Open the browser to the dashboard (e.g. `http://localhost:8000`).
- Explain the UI: "This is a lightning-fast Vanilla JS single-page application. No build steps, no heavy frameworks."
- Run `python scripts/fire_disputes.py` to blast 5 synthetic disputes at the webhook endpoint.
- Watch the dashboard populate in real-time.
- Click on a dispute with a green badge (e.g., `Win Prob > 0.723`).
- **Show the detail view:**
  - Highlight the `Evidence Bundle` on the left.
  - Read the `Draft Rebuttal` on the right. Point out the citation chips (e.g. `[shipment.pod_id]`).
  - Hover over a citation chip to show it dynamically highlighting the verified fact in the evidence bundle.
  - Note that the status says **Submitted ✓**, meaning no human intervention was required!

## 1:30 - 3:00: The Failure Path (Catching LLM Hallucinations)
- Find a dispute in the dashboard whose `Audit Trail` contains a `draft_rejected` event.
- **Walk through the Audit Trail:**
  1. `received`: The webhook came in.
  2. `scored`: XGBoost rated it a highly winnable dispute.
  3. `draft_rejected`: Explain what happened here. "The LLM hallucinated a citation. It tried to claim a tracking number was present but failed to actually write the tracking number in the text. Our deterministic Python Regex validator caught the lie."
  4. Explain the self-healing loop: "The system automatically fed the Python validation error back into the LLM prompt and commanded it to rewrite the draft."
  5. `submitted`: Show that 10 seconds later, the LLM successfully regenerated a fully-compliant draft on the second try and it was automatically submitted.

## 3:00 - 4:00: The Human Review Gate
- Click on a dispute with a red `human_review` badge.
- Explain *why* it was gated. Look at the `gate_reason` below the progress bar (e.g., `low_confidence_0.631`).
- Explain the ML fallback: "The XGBoost model detected that the customer has a history of prior disputes, dropping our win probability below our dynamically calculated threshold. Instead of risking a $15 false-positive fee, it paused the dispute for a human."
- Click the blue `Approve & Submit →` button to manually override the system and submit it.

## 4:00 - 5:00: Metrics & Architecture
- Open `METRICS.md` in your IDE.
- Briefly explain the batch simulation: "We ran this exact pipeline over our frozen held-out dataset. Here is exactly how much INR we would have recovered compared to 'Contest Everything' or 'Contest Nothing'."
- Point to the specific False Positive and False Negative case studies to demonstrate that the errors are honest and analytically understood.
- End the video on the `ARCHITECTURE.md` Mermaid diagram.
