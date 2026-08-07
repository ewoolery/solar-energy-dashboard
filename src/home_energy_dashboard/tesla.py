from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import Settings


AUTH_URL = "https://auth.tesla.com/oauth2/v3/authorize"
TOKEN_URL = "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token"
SCOPES = "openid offline_access energy_device_data"


@dataclass(frozen=True)
class LiveSample:
    solar_kw: float
    home_kw: float
    grid_kw: float
    battery_kw: float
    battery_soc: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def authorization_url(settings: Settings, state: str) -> str:
    params = {
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "prompt_missing_scopes": "true",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


class TeslaClient:
    def __init__(self, settings: Settings, access_token: str | None = None) -> None:
        self.settings = settings
        self.access_token = access_token

    async def exchange_code(self, code: str) -> dict[str, Any]:
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret,
            "code": code,
            "audience": self.settings.audience,
            "redirect_uri": self.settings.redirect_uri,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(TOKEN_URL, data=payload)
            response.raise_for_status()
            return response.json()

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.settings.client_id,
            "refresh_token": refresh_token,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(TOKEN_URL, data=payload)
            response.raise_for_status()
            return response.json()

    async def get(self, path: str) -> Any:
        if not self.access_token:
            raise RuntimeError("Tesla access token is missing")
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        url = f"{self.settings.api_base_url.rstrip('/')}{path}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json().get("response")

    async def energy_sites(self) -> list[dict[str, Any]]:
        products = await self.get("/api/1/products")
        return [
            product
            for product in products
            if product.get("energy_site_id") is not None
        ]

    async def live_status(self, energy_site_id: int) -> dict[str, Any]:
        return await self.get(f"/api/1/energy_sites/{energy_site_id}/live_status")


def normalize_live_status(payload: dict[str, Any]) -> LiveSample:
    """Normalize Tesla watts to kW while preserving Tesla's reported signs.

    Sign direction must be checked against the Tesla app before assigning semantic
    import/export or charge/discharge labels in the UI.
    """
    return LiveSample(
        solar_kw=float(payload.get("solar_power", 0)) / 1000,
        home_kw=float(payload.get("load_power", 0)) / 1000,
        grid_kw=float(payload.get("grid_power", 0)) / 1000,
        battery_kw=float(payload.get("battery_power", 0)) / 1000,
        battery_soc=float(payload.get("percentage_charged", 0)),
    )

