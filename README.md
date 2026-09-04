# CaseClosed

I built CaseClosed to automate chargeback dispute defense. The system listens for Razorpay webhooks, automatically pulls delivery and chat evidence from the database, and uses an LLM to generate formal rebuttals. It catches its own hallucinations through a strict citation validation loop and automatically submits high-confidence wins to Razorpay while routing uncertain cases to a human.

## Setup

1. Copy `.env.example` to `.env` and set your API keys.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Boot the server and dashboard:
   ```bash
   python main.py
   ```

## Documentation
- **Architecture**: See `ARCHITECTURE.md` for a technical breakdown of the pipeline.
- **Metrics**: See `METRICS.md` for performance on the held-out dataset and error analysis.
