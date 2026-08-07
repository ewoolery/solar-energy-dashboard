from dataclasses import dataclass
import os

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    client_id: str = os.getenv("TESLA_CLIENT_ID", "")
    client_secret: str = os.getenv("TESLA_CLIENT_SECRET", "")
    redirect_uri: str = os.getenv("TESLA_REDIRECT_URI", "http://localhost:8000/callback")
    audience: str = os.getenv(
        "TESLA_AUDIENCE", "https://fleet-api.prd.na.vn.cloud.tesla.com"
    )
    api_base_url: str = os.getenv(
        "TESLA_API_BASE_URL", "https://fleet-api.prd.na.vn.cloud.tesla.com"
    )
    database_path: str = os.getenv("DATABASE_PATH", "energy.sqlite3")
    timezone: str = os.getenv("TIMEZONE", "America/Los_Angeles")
    # Seconds between background live samples. 0 disables the poller (the
    # default, for local dev); a headless deployment sets e.g. 60.
    sample_interval_seconds: int = int(os.getenv("SAMPLE_INTERVAL_SECONDS", "0") or 0)
    # ntfy.sh push notification for "Powerwall full". Leave topic blank to
    # disable. Fires once when SOC crosses full_pct, re-arms below rearm_pct.
    ntfy_server: str = os.getenv("NTFY_SERVER", "https://ntfy.sh")
    ntfy_topic: str = os.getenv("NTFY_TOPIC", "")
    battery_full_pct: float = float(os.getenv("BATTERY_FULL_PCT", "99.5") or 99.5)
    battery_rearm_pct: float = float(os.getenv("BATTERY_REARM_PCT", "95") or 95)

    @property
    def oauth_ready(self) -> bool:
        return bool(self.client_id and self.client_secret)


settings = Settings()

