import json
import pickle
from pathlib import Path
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV
from sqlalchemy.orm import Session
from .db import SessionLocal, Dispute
from .features import build_feature_matrix
from .config import config

_REPO_ROOT = Path(__file__).parent.parent.parent
CLASSIFIER_PATH = _REPO_ROOT / "data" / "classifier.pkl"
METRICS_PATH = _REPO_ROOT / "data" / "metrics.json"


class DisputeClassifier:
    def __init__(self):
        self.model = None
        self.feature_columns = None

    def train(self, X, y, feature_columns):
        """Train gradient boosting with calibration."""
        self.feature_columns = feature_columns
        base = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            random_state=42
        )
        self.model = CalibratedClassifierCV(base, method="sigmoid", cv=3)
        self.model.fit(X, y)

    def predict_proba(self, X):
        """Return win probability."""
        if self.model is None:
            raise ValueError("model not trained")
        return self.model.predict_proba(X)[:, 1]


def sweep_threshold(y_true, y_pred_proba, mean_amount, fp_cost):
    """Find optimal threshold minimizing expected cost."""
    thresholds = np.linspace(0.05, 0.95, 100)
    results = []

    for thresh in thresholds:
        y_pred = (y_pred_proba >= thresh).astype(int)

        tp = np.sum((y_pred == 1) & (y_true == 1))
        fp = np.sum((y_pred == 1) & (y_true == 0))
        tn = np.sum((y_pred == 0) & (y_true == 0))
        fn = np.sum((y_pred == 0) & (y_true == 1))

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        cost = fp * fp_cost + fn * mean_amount

        results.append({
            "threshold": thresh,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "cost": cost,
            "tp": int(tp),
            "fp": int(fp),
            "tn": int(tn),
            "fn": int(fn)
        })

    best = min(results, key=lambda x: x["cost"])
    return best["threshold"], results


def train_and_save():
    """Train on the frozen train split, evaluate on held-out, save both artefacts.

    Must be called from generator.py (or any importer), never run as __main__,
    so DisputeClassifier is always pickled as chargeback.model.DisputeClassifier.
    """
    session = SessionLocal()
    try:
        train_disputes = session.query(Dispute).filter_by(split="train").all()
        held_disputes = session.query(Dispute).filter_by(split="held_out").all()

        print(f"  training on {len(train_disputes)} disputes, "
              f"evaluating on {len(held_disputes)} held-out")

        import pandas as pd
        from .features import _build_rows
        rows, y_train = _build_rows(train_disputes, session)
        df = pd.DataFrame(rows)
        df = pd.get_dummies(df, columns=["dispute_type", "delivery_status_final"], drop_first=False)
        for col in df.columns:
            if df[col].dtype == bool:
                df[col] = df[col].astype(int)
        feature_columns = list(df.columns)
        X_train = df.values
        y_train = np.array(y_train)

        clf = DisputeClassifier()
        clf.train(X_train, y_train, feature_columns)

        # threshold sweep on train set only
        train_proba = clf.predict_proba(X_train)
        mean_amount = float(np.mean([d.amount for d in train_disputes]))
        best_thresh, _ = sweep_threshold(y_train, train_proba, mean_amount, config.fp_cost_inr)

        # evaluate on frozen held-out
        X_held, y_held = build_feature_matrix(held_disputes, session, expected_columns=feature_columns)
        held_proba = clf.predict_proba(X_held)
        y_pred = (held_proba >= best_thresh).astype(int)

        tp = int(np.sum((y_pred == 1) & (y_held == 1)))
        fp = int(np.sum((y_pred == 1) & (y_held == 0)))
        fn = int(np.sum((y_pred == 0) & (y_held == 1)))
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        print(f"  held-out  precision={precision:.3f}  recall={recall:.3f}  "
              f"threshold={best_thresh:.3f}")

        CLASSIFIER_PATH.parent.mkdir(exist_ok=True)
        with open(CLASSIFIER_PATH, "wb") as f:
            pickle.dump(clf, f)

        metrics = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "threshold": round(float(best_thresh), 4),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "held_out_n": len(held_disputes),
        }
        with open(METRICS_PATH, "w") as f:
            json.dump(metrics, f, indent=2)

        print(f"  saved classifier -> {CLASSIFIER_PATH}")
        print(f"  saved metrics    -> {METRICS_PATH}")

        # Save held out probabilities back to DB for the metrics report to use
        for d, prob in zip(held_disputes, held_proba):
            d.win_prob = float(prob)
        session.commit()

        return precision, recall, best_thresh

    finally:
        session.close()
