import json
from datetime import datetime
from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent.parent
AUDIT_FILE = _REPO_ROOT / "logs" / "audit.jsonl"


def log_audit(
    dispute_id: str,
    action: str,
    win_prob: float | None = None,
    basis: list[str] | None = None,
    actor: str = "system",
    detail: str | None = None
):
    AUDIT_FILE.parent.mkdir(exist_ok=True)

    entry = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "dispute_id": dispute_id,
        "action": action,
        "win_prob": win_prob,
        "basis": basis or [],
        "actor": actor,
        "detail": detail
    }

    with open(AUDIT_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
