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

    @property
    def oauth_ready(self) -> bool:
        return bool(self.client_id and self.client_secret)


settings = Settings()

