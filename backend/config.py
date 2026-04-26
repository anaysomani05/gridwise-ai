from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Always load `.env` next to this file (works no matter what the process cwd is).
_ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Electricity Maps — set in .env when you wire the live client
    electricity_maps_api_token: str | None = None
    electricity_maps_base_url: str = "https://api.electricitymaps.com/v3"

    # Talk-to-agent: backend proxies POST /chat → agent layer (same host the UI uses for /optimize)
    agent_service_url: str = "http://127.0.0.1:8001"

    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5500,http://127.0.0.1:5500,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
