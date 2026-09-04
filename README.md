# CaseClosed
### THEME - AI Risk Manager

I built CaseClosed to automate chargeback dispute defense. The system listens for Razorpay webhooks, automatically pulls delivery and chat evidence from the database, and uses an LLM to generate formal rebuttals. It catches its own hallucinations through a strict citation validation loop and automatically submits high-confidence wins to Razorpay while routing uncertain cases to a human.


## How to Run Locally

1. **Environment Setup**
   Copy `.env.example` to `.env` and insert your Gemini API Key.
   
2. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Generate Synthetic World & Train Classifier**
   Before starting the server, you need to generate the synthetic orders, customers, and shipments, and train the Gradient Boosting model on the data:
   ```bash
   python run_generator.py
   ```
   *(This populates the local SQLite database and saves `data/classifier.pkl` and `data/metrics.json`)*

4. **Boot the API Server & Dashboard**
   - Windows: `python main.py`
   - Mac/Linux: `make run`
   
   The dashboard is now live at **[http://localhost:8000](http://localhost:8000)**.

5. **Fire Simulated Razorpay Webhooks**
   In a *new* terminal window, run the script to simulate incoming Razorpay disputes:
   ```bash
   python scripts/fire_disputes.py
   ```
   *Watch the dashboard to see the system instantly score, gate, and auto-draft rebuttals for the incoming disputes in real-time!*

## Documentation
- **Architecture**: See `ARCHITECTURE.md` for a technical breakdown of the pipeline.
- **Metrics**: See `METRICS.md` for performance on the held-out dataset and error analysis.


## The "2 AM" Moments: What Broke & How We Fixed It
Building an autonomous financial agent meant we had to deal with concurrency and LLM unpredictability. Here are the two biggest walls we hit, and how we broke through them:

### 1. The Concurrency Crash (The SQLite Trap)
What broke: Early in the build, we used SQLite for our local database. It worked perfectly for single requests. But when we wrote a load-testing script to simulate a burst of 10 simultaneous webhook disputes from Razorpay, the entire backend locked up. Python's SQLAlchemy threads were crashing into SQLite's database is locked error, even with Write-Ahead Logging (WAL) enabled. How we got out: At 2 AM, we made the hard pivot to drop SQLite entirely. We migrated the schema to Supabase (PostgreSQL), refactored our connection pooling, and switched to async SQLAlchemy sessions. The system can now handle massive bursts of concurrent webhooks without dropping a single dispute.

### 2. The Hallucination Loop
What broke: We quickly realized that LLMs are terrible at deterministic tasks. Even Gemini 2.5 Flash, heavily prompted, would sometimes hallucinate citations. It would write "The package was tracked via [source: shipment.tracking_id]" but completely forget to actually put the real tracking number in the sentence. If that went to the bank, we'd lose the case instantly. How we got out: We stopped trying to solve an engineering problem with "better prompting." Instead, we built a deterministic Python Regex Validator. The validator acts as a firewall between the LLM and Razorpay. It parses every citation chip, cross-references it against the raw database features, and if the LLM hallucinated, the Python script blocks the submission and forces the LLM to rewrite the draft until it's mathematically perfect.
