from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/job_scheduler"
    WORKER_COUNT: int = 2
    WORKER_POLL_INTERVAL: float = 0.5      # seconds between polls
    STARVATION_CHECK_INTERVAL: float = 30  # seconds between starvation checks
    DLQ_ALERT_THRESHOLD: int = 10          # DLQ jobs before alert fires
    # Starvation thresholds (minutes before boosting kicks in)
    STARVATION_LOW_MINUTES: int = 5        # Low-priority jobs boosted after 5 min
    STARVATION_MEDIUM_MINUTES: int = 10    # Medium-priority jobs boosted after 10 min
    STARVATION_MAX_MINUTES: int = 15       # Any job reaches priority 1 after 15 min
    # Webhook handler settings
    WEBHOOK_TIMEOUT: float = 10.0          # seconds
    WEBHOOK_MAX_REDIRECTS: int = 3
    # Alert email (simulated)
    ALERT_EMAIL: str = "akinolatofunmi.tech@gmail.com"


settings = Settings()
