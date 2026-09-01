from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # database
    database_url: str = "sqlite:///chargeback.db"

    # razorpay
    razorpay_key_id: str = "rzp_test_placeholder"
    razorpay_key_secret: str = "placeholder_secret"
    razorpay_webhook_secret: str = "webhook_secret_placeholder"

    # ngrok
    ngrok_expose_url: str = "augmentable-kathline-diffidently.ngrok-free.dev/webhooks/razorpay"

    # llm
    llm_provider: str = "anthropic"  # anthropic | openai | gemini
    llm_model: str = "claude-sonnet-4-20250514"
    llm_api_key: str = "placeholder_key"
    llm_timeout_seconds: int = 30

    # classifier
    fp_cost_inr: float = 2000.0

    # server
    host: str = "0.0.0.0"
    port: int = 8000


config = Config()
