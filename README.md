# CaseClosed
### THEME - AI Risk Manager

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


## The "2 AM" Moments: What Broke & How We Fixed It
Building an autonomous financial agent meant we had to deal with concurrency and LLM unpredictability. Here are the two biggest walls we hit, and how we broke through them:

### 1. The Concurrency Crash (The SQLite Trap)
What broke: Early in the build, we used SQLite for our local database. It worked perfectly for single requests. But when we wrote a load-testing script to simulate a burst of 10 simultaneous webhook disputes from Razorpay, the entire backend locked up. Python's SQLAlchemy threads were crashing into SQLite's database is locked error, even with Write-Ahead Logging (WAL) enabled. How we got out: At 2 AM, we made the hard pivot to drop SQLite entirely. We migrated the schema to Supabase (PostgreSQL), refactored our connection pooling, and switched to async SQLAlchemy sessions. The system can now handle massive bursts of concurrent webhooks without dropping a single dispute.

### 2. The Hallucination Loop
What broke: We quickly realized that LLMs are terrible at deterministic tasks. Even Gemini 2.5 Flash, heavily prompted, would sometimes hallucinate citations. It would write "The package was tracked via [source: shipment.tracking_id]" but completely forget to actually put the real tracking number in the sentence. If that went to the bank, we'd lose the case instantly. How we got out: We stopped trying to solve an engineering problem with "better prompting." Instead, we built a deterministic Python Regex Validator. The validator acts as a firewall between the LLM and Razorpay. It parses every citation chip, cross-references it against the raw database features, and if the LLM hallucinated, the Python script blocks the submission and forces the LLM to rewrite the draft until it's mathematically perfect.
