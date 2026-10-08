from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://recoverly:recoverly@localhost:5432/recoverly"

    paypal_base_url: str = "https://api-m.sandbox.paypal.com"
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""
    allow_simulator: bool = False

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""

    openai_api_key: str = ""
    deepgram_api_key: str = ""
    cartesia_api_key: str = ""

    public_base_url: str = "http://localhost:8000"
    time_scale: float = 1.0
    abandon_after_seconds: float = 900.0  # real time; set 90 for the demo
    kill_switch: bool = False


settings = Settings()
