import json
from pathlib import Path
from sqlalchemy.orm import Session
from chargeback.db import engine, Dispute
from chargeback.config import config

def generate_report():
    metrics_file = Path("data/metrics.json")
    if not metrics_file.exists():
        print("data/metrics.json not found. Run generator first.")
        return
        
    with open(metrics_file) as f:
        metrics = json.load(f)
        
    threshold = metrics["threshold"]
    
    with Session(engine) as session:
        held_out = session.query(Dispute).filter_by(split="held_out").all()
        
        # Batch simulation
        our_recovered = 0.0
        contest_all_recovered = 0.0
        
        contested_count = 0
        total_held_out = len(held_out)
        
        misclassified = []
        
        for d in held_out:
            prob = d.win_prob if d.win_prob is not None else 0.0
            we_contest = prob >= threshold
            label_won = (d.label == "merchant_won")
            
            # Contest all baseline
            if label_won:
                contest_all_recovered += d.amount
            else:
                contest_all_recovered -= config.fp_cost_inr
                
            # Our system
            if we_contest:
                contested_count += 1
                if label_won:
                    our_recovered += d.amount
                else:
                    our_recovered -= config.fp_cost_inr
                    misclassified.append((d, "Contested but lost (False Positive)"))
            else:
                if label_won:
                    misclassified.append((d, "Dropped but would have won (False Negative)"))
                    
        # Output Markdown
        md = [
            "# Dispute Defense Metrics",
            "",
            "## Held-out Evaluation",
            "",
            f"- **Threshold**: `{threshold:.3f}`",
            f"- **Precision**: `{metrics.get('precision', 0):.3f}`",
            f"- **Recall**: `{metrics.get('recall', 0):.3f}`",
            f"- **F1 Score**: `{metrics.get('f1', 0):.3f}`",
            "",
            "## Batch Recovery Simulation",
            "",
            "Performance on the frozen held-out set simulating INR recovered.",
            "",
            "| Strategy | INR Recovered | Auto-Response Rate |",
            "|----------|---------------|--------------------|",
            f"| **Our System (AI)** | ₹{our_recovered:,.2f} | {(contested_count / total_held_out * 100) if total_held_out else 0:.1f}% |",
            f"| **Contest Everything** | ₹{contest_all_recovered:,.2f} | 100% |",
            f"| **Contest Nothing** | ₹0.00 | 0% |",
            "",
            "## Examples of Misclassifications",
            ""
        ]
        
        for m in misclassified[:3]:
            d, reason = m
            md.extend([
                f"### {d.dispute_id} ({d.dispute_type})",
                f"- **Error Type**: {reason}",
                f"- **Amount**: ₹{d.amount:,.2f}",
                f"- **Model Prob**: {d.win_prob:.3f}" if d.win_prob is not None else "- **Model Prob**: None",
                f"- **Actual Label**: {d.label}",
                ""
            ])
            
        with open("METRICS.md", "w", encoding="utf-8") as f:
            f.write("\n".join(md))
            
        print("Wrote METRICS.md successfully.")

if __name__ == "__main__":
    generate_report()
