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

    # voice agent
    llm_model: str = "gpt-4.1-mini"
    stt_model: str = "nova-3"
    tts_voice_id: str = "71a7ad14-091c-4e8e-a314-022ece01c121"  # a Cartesia stock voice
    call_max_seconds: int = 180        # spend cap: hard 3-minute call cap
    ring_timeout_seconds: int = 45     # unanswered browser call -> no_answer
    max_concurrent_calls: int = 3
    silence_timeout_seconds: int = 25
    turn_ice_urls: str = ""            # comma-separated, e.g. turn:host:3478
    turn_username: str = ""
    turn_credential: str = ""
    demo_buyer_email: str = ""        # shown on the demo page for judges (sandbox only)
    demo_buyer_password: str = ""

    @property
    def voice_enabled(self) -> bool:
        return bool(self.openai_api_key and self.deepgram_api_key and self.cartesia_api_key)


settings = Settings()
