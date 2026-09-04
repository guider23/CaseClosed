from fastapi import FastAPI, Request, HTTPException, Response, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
import pickle
from pathlib import Path

from .config import config
from .db import engine, Dispute
from .ingest import verify_webhook_signature, ingest_dispute
from .evidence import build_evidence_bundle
from .features import extract_features, build_feature_matrix
from .compose import LLMComposer
from .validate import validate_citations
from .gate import should_gate_to_human
from .audit import log_audit
from .validate import validate_citations
from .razorpay_client import RazorpayClient, RazorpayError


app = FastAPI(title="CaseClosed API")

_REPO_ROOT = Path(__file__).parent.parent.parent
CLASSIFIER_PATH = _REPO_ROOT / "data" / "classifier.pkl"
METRICS_PATH = _REPO_ROOT / "data" / "metrics.json"
STATIC_DIR = _REPO_ROOT / "static"
_CLASSIFIER = None


def _load_metrics() -> dict:
    if METRICS_PATH.exists():
        import json
        with open(METRICS_PATH) as f:
            return json.load(f)
    return {"threshold": 0.5, "precision": None, "recall": None}


THRESHOLD = _load_metrics()["threshold"]


def get_classifier():
    global _CLASSIFIER
    if _CLASSIFIER is None:
        with open(CLASSIFIER_PATH, "rb") as f:
            _CLASSIFIER = pickle.load(f)
    return _CLASSIFIER


@app.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not verify_webhook_signature(body, signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        import json
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=422, detail="malformed json")

    with Session(engine) as session:
        try:
            dispute = ingest_dispute(payload, session)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        if not dispute:
            return Response(status_code=200, content="duplicate")

        # if order not matched, acknowledge and stop
        if dispute.status == "unmatched_order":
            return {"status": "received", "dispute_id": dispute.dispute_id, "note": "unmatched order"}

        # acknowledge immediately, process in background
        background_tasks.add_task(process_dispute_sync, dispute.dispute_id)

        return {"status": "received", "dispute_id": dispute.dispute_id}


def process_dispute_sync(dispute_id: str):
    """Background processing: score, evidence, compose."""
    try:
        # score
        with Session(engine) as session:
            dispute = session.query(Dispute).filter_by(dispute_id=dispute_id).first()
            if not dispute:
                return

            classifier = get_classifier()
            X, _ = build_feature_matrix([dispute], session, expected_columns=classifier.feature_columns)
            win_prob = float(classifier.predict_proba(X)[0])

            dispute.win_prob = win_prob
            session.commit()

        log_audit(dispute_id, "scored", win_prob=win_prob)

        # build evidence
        with Session(engine) as session:
            dispute = session.query(Dispute).filter_by(dispute_id=dispute_id).first()
            bundle = build_evidence_bundle(dispute, session)
            dispute.evidence_bundle = bundle
            session.commit()

        # gate
        with Session(engine) as session:
            dispute = session.query(Dispute).filter_by(dispute_id=dispute_id).first()
            should_gate, gate_reason = should_gate_to_human(dispute, dispute.evidence_bundle, THRESHOLD)

            if should_gate:
                dispute.status = "human_review"
                dispute.gate_reason = gate_reason
                log_audit(dispute_id, "gated_human", detail=gate_reason)
                session.commit()
                return
            session.commit()

        # compose
        with Session(engine) as session:
            dispute = session.query(Dispute).filter_by(dispute_id=dispute_id).first()
            composer = LLMComposer()
            draft_response = composer.compose(dispute.evidence_bundle, dispute)
            draft = draft_response.text

            # validate
            validation = validate_citations(draft, dispute.evidence_bundle)

            if not validation.valid:
                log_audit(dispute_id, "draft_rejected", detail="; ".join(validation.errors))

                # regenerate once
                feedback = "\n".join(validation.errors)
                draft_response = composer.compose(dispute.evidence_bundle, dispute, validation_feedback=feedback)
                draft = draft_response.text

                validation = validate_citations(draft, dispute.evidence_bundle)

                if not validation.valid:
                    dispute.status = "human_review"
                    dispute.gate_reason = "composer_validation_failed"
                    log_audit(dispute_id, "gated_human", detail="validation failed twice")

            dispute.draft = draft
            session.commit()
            log_audit(dispute_id, "auto_drafted", detail=f"model={draft_response.model}")

            if dispute.status == "received":
                try:
                    from chargeback.razorpay_client import RazorpayClient
                    client = RazorpayClient()
                    client.submit_contest(dispute_id, draft, action="draft")
                    dispute.status = "submitted"
                    session.commit()
                    log_audit(dispute_id, "submitted", actor="system", detail="auto-submitted")
                except Exception as e:
                    dispute.status = "human_review"
                    dispute.gate_reason = f"auto_submit_failed: {str(e)}"
                    session.commit()
                    log_audit(dispute_id, "gated_human", detail=f"auto_submit_failed: {str(e)}")

    except Exception as e:
        with Session(engine) as session:
            dispute = session.query(Dispute).filter_by(dispute_id=dispute_id).first()
            if dispute:
                dispute.status = "human_review"
                dispute.gate_reason = f"processing_error: {str(e)}"
                session.commit()
        log_audit(dispute_id, "gated_human", detail=str(e))


@app.delete("/disputes")
def delete_all_disputes():
    with Session(engine) as session:
        session.query(Dispute).delete()
        session.commit()
    return {"status": "cleared"}

@app.get("/disputes")
def list_disputes(status: str | None = None):
    with Session(engine) as session:
        # Only show live disputes (split is None) in the dashboard
        query = session.query(Dispute).filter(Dispute.split.is_(None))
        if status:
            query = query.filter(Dispute.status == status)

        disputes = query.order_by(Dispute.respond_by).all()

        return [
            {
                "dispute_id": d.dispute_id,
                "order_id": d.order_id,
                "type": d.dispute_type,
                "amount": d.amount,
                "currency": d.currency,
                "raised_at": d.raised_at.isoformat(),
                "respond_by": d.respond_by.isoformat(),
                "status": d.status,
                "win_prob": d.win_prob,
                "gate_reason": d.gate_reason
            }
            for d in disputes
        ]


@app.get("/disputes/{dispute_id}")
def get_dispute(dispute_id: str):
    with Session(engine) as session:
        dispute = session.query(Dispute).filter_by(dispute_id=dispute_id).first()

        if not dispute:
            raise HTTPException(status_code=404, detail="not found")

        from .audit import AUDIT_FILE
        audit_lines = []
        if AUDIT_FILE.exists():
            with open(AUDIT_FILE) as f:
                for line in f:
                    import json
                    try:
                        entry = json.loads(line)
                        if entry["dispute_id"] == dispute_id:
                            audit_lines.append(entry)
                    except ValueError:
                        pass

        return {
            "dispute_id": dispute.dispute_id,
            "payment_id": dispute.payment_id,
            "order_id": dispute.order_id,
            "type": dispute.dispute_type,
            "reason_code": dispute.reason_code,
            "amount": dispute.amount,
            "currency": dispute.currency,
            "raised_at": dispute.raised_at.isoformat(),
            "respond_by": dispute.respond_by.isoformat(),
            "status": dispute.status,
            "win_prob": dispute.win_prob,
            "gate_reason": dispute.gate_reason,
            "draft": dispute.draft,
            "evidence_bundle": dispute.evidence_bundle,
            "audit": audit_lines
        }


@app.post("/disputes/{dispute_id}/draft")
def generate_draft(dispute_id: str):
    with Session(engine) as session:
        dispute = session.query(Dispute).filter_by(dispute_id=dispute_id).first()
        if not dispute:
            raise HTTPException(status_code=404, detail="not found")
        if dispute.draft:
            return {"status": "already_drafted", "draft": dispute.draft}
            
        composer = LLMComposer()
        draft_response = composer.compose(dispute.evidence_bundle, dispute)
        draft = draft_response.text

        validation = validate_citations(draft, dispute.evidence_bundle)
        if not validation.valid:
            log_audit(dispute_id, "draft_rejected", detail="; ".join(validation.errors))
            feedback = "\n".join(validation.errors)
            draft_response = composer.compose(dispute.evidence_bundle, dispute, validation_feedback=feedback)
            draft = draft_response.text
            validation = validate_citations(draft, dispute.evidence_bundle)
            if not validation.valid:
                log_audit(dispute_id, "manual_draft_failed", detail="validation failed twice")
                raise HTTPException(status_code=422, detail="Failed to generate valid citations")

        dispute.draft = draft
        session.commit()
        log_audit(dispute_id, "manual_drafted", detail=f"model={draft_response.model}")
        return {"status": "drafted", "draft": draft}


@app.post("/disputes/{dispute_id}/approve")
def approve_dispute(dispute_id: str):
    with Session(engine) as session:
        dispute = session.query(Dispute).filter_by(dispute_id=dispute_id).first()

        if not dispute:
            raise HTTPException(status_code=404)
        if dispute.status == "submitted":
            raise HTTPException(status_code=400, detail="already submitted")

        client = RazorpayClient()
        
        try:
            # We use action="draft" for the hackathon demo compromise (safe).
            client.submit_contest(dispute_id, dispute.draft or "", action="draft")
            
            dispute.status = "submitted"
            session.commit()
            log_audit(dispute_id, "submitted", actor="human")
            return {"status": "submitted"}
        except RazorpayError as e:
            dispute.status = "human_review" # Revert or keep in human review
            session.commit()
            log_audit(dispute_id, "submit_failed", actor="human", detail=str(e))
            raise HTTPException(status_code=400, detail=str(e))


@app.post("/disputes/{dispute_id}/escalate")
def escalate_dispute(dispute_id: str):
    with Session(engine) as session:
        dispute = session.query(Dispute).filter_by(dispute_id=dispute_id).first()
        if not dispute:
            raise HTTPException(status_code=404)
        if dispute.status == "submitted":
            raise HTTPException(status_code=400, detail="cannot escalate submitted dispute")

        dispute.status = "human_review"
        session.commit()

        log_audit(dispute_id, "escalated", actor="human")

        return {"status": "escalated"}


@app.get("/stats")
def get_stats():
    with Session(engine) as session:
        # Only count live disputes for the UI stats
        disputes = session.query(Dispute).filter(Dispute.split.is_(None)).all()

        total_amount = sum(d.amount for d in disputes)
        auto_count = sum(1 for d in disputes if d.status == "auto_drafted")
        human_count = sum(1 for d in disputes if d.status == "human_review")

        # real held-out metrics from data/metrics.json
        m = _load_metrics()
        held_out_precision = m.get("precision")
        held_out_recall = m.get("recall")

        return {
            "total_disputes": len(disputes),
            "total_amount_inr": round(total_amount, 2),
            "auto_response_rate": round(auto_count / len(disputes), 3) if disputes else 0,
            "human_review_count": human_count,
            "held_out_precision": held_out_precision,
            "held_out_recall": held_out_recall
        }


@app.get("/")
def dashboard():
    return FileResponse(str(STATIC_DIR / "index.html"))


# Mount static files last
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
