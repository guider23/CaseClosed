from .db import Dispute


def should_gate_to_human(dispute: Dispute, bundle: dict, threshold: float) -> tuple[bool, str | None]:
    """Returns (should_gate, reason)."""

    if dispute.win_prob is None:
        return True, "missing_score"

    if dispute.win_prob < threshold:
        return True, f"low_confidence_{dispute.win_prob:.3f}"

    if dispute.dispute_type == "item_not_received":
        if "shipment.pod_id" not in bundle:
            return True, "missing_pod"

    if dispute.dispute_type == "unauthorized":
        if "order.id" not in bundle:
            return True, "missing_payment_metadata"

    return False, None
