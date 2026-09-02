import os
import sys
from pathlib import Path
from sqlalchemy import create_engine, text

# Add src to path so we can import config
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from chargeback.config import config

def clear_live_disputes():
    database_url = config.database_url
    if database_url:
        database_url = database_url.replace("postgres://", "postgresql://")
    
    print(f"Connecting to Postgres to clear live disputes...")

    try:
        engine = create_engine(database_url)
        with engine.begin() as conn:
            # Delete only disputes that do NOT have a split (live dashboard disputes)
            conn.execute(text("DELETE FROM disputes WHERE split IS NULL;"))
            print("Successfully deleted all live disputes from the dashboard!")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    clear_live_disputes()
