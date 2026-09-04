import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from chargeback.config import config
import logging

logger = logging.getLogger(__name__)


class RazorpayError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Razorpay API Error {status_code}: {message}")


class RazorpayClient:
    def __init__(self):
        self.base_url = "https://api.razorpay.com/v1"
        self.auth = httpx.BasicAuth(config.razorpay_key_id, config.razorpay_key_secret)
        # We share a timeout configuration across the client
        self.timeout = httpx.Timeout(30.0)

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=2, min=4, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.TimeoutException)),
        reraise=True
    )
    def fetch_dispute(self, dispute_id: str) -> dict:
        """
        Fetches the dispute from Razorpay.
        """
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(
                    f"{self.base_url}/disputes/{dispute_id}",
                    auth=self.auth
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            # Handle the demo case where the dispute ID is synthetic
            if e.response.status_code == 404 and (dispute_id.startswith("disp_000") or dispute_id.startswith("disp_demo_")):
                logger.warning(f"Simulating fetch_dispute for synthetic ID: {dispute_id}")
                # Exact schema mock as per Razorpay documentation
                return {
                    "id": dispute_id,
                    "entity": "dispute",
                    "amount": 1000,
                    "currency": "INR",
                    "status": "open",
                    "phase": "chargeback",
                    "reason_code": "fraud",
                    "reason_description": "Simulated dispute for demo",
                    "respond_by": 1735689600,
                    "created_at": 1704067200,
                    "evidence": {}
                }
            
            # Real errors
            error_msg = e.response.text
            try:
                error_msg = e.response.json().get("error", {}).get("description", e.response.text)
            except Exception:
                pass
            raise RazorpayError(e.response.status_code, error_msg)

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=2, min=4, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.TimeoutException)),
        reraise=True
    )
    def submit_contest(self, dispute_id: str, summary: str, amount: int, simulated_evidence: dict, action: str = "draft") -> dict:
        """
        Contests the dispute on Razorpay. action can be 'draft' or 'submit'.
        """
        try:
            payload = {
                "amount": amount,
                "summary": summary,
                "action": action
            }
            if simulated_evidence:
                payload.update(simulated_evidence)
                
            with httpx.Client(timeout=self.timeout) as client:
                response = client.patch(
                    f"{self.base_url}/disputes/{dispute_id}/contest",
                    auth=self.auth,
                    json=payload
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            # Handle the Hackathon Demo Compromise
            # If we get a 404 and it's our synthetic ID, we pretend it worked so the UI demo is smooth.
            if e.response.status_code == 404 and (dispute_id.startswith("disp_000") or dispute_id.startswith("disp_demo_")):
                logger.warning(f"Simulated Razorpay contest submission for synthetic ID: {dispute_id}")
                return {"status": "submitted_to_bank_simulated"}

            # For real failures (e.g. 401 Unauthorized, 400 Bad Request)
            error_msg = e.response.text
            try:
                error_msg = e.response.json().get("error", {}).get("description", e.response.text)
            except Exception:
                pass
            raise RazorpayError(e.response.status_code, error_msg)

