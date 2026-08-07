from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
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


def stamp_expiry(tokens: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a copy of a token payload with an absolute ``expires_at`` (UTC ISO).

    Tesla returns a relative ``expires_in`` (seconds). A refresh response may omit
    ``refresh_token``; in that case we keep the prior one so the chain survives.
    """
    stamped = dict(tokens)
    expires_in = int(tokens.get("expires_in", 0) or 0)
    stamped["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    ).isoformat()
    if not stamped.get("refresh_token") and previous:
        stamped["refresh_token"] = previous.get("refresh_token")
    return stamped


def is_expired(tokens: dict[str, Any], skew: int = 60) -> bool:
    """True if the access token is missing/expired (``skew`` seconds of safety)."""
    expires_at = tokens.get("expires_at")
    if not expires_at:
        return True
    deadline = datetime.fromisoformat(expires_at) - timedelta(seconds=skew)
    return datetime.now(timezone.utc) >= deadline


def summarize_energy_history(payload: dict[str, Any]) -> dict[str, float]:
    """Aggregate a ``calendar_history`` (kind=energy) response into kWh totals.

    Tesla reports cumulative Wh fields per time bucket; we sum the buckets and
    convert to kWh, preserving the same sign convention documented in rates.py.
    """
    buckets = (payload or {}).get("time_series") or []

    def total(*keys: str) -> float:
        return sum(
            float(bucket.get(key, 0) or 0)
            for bucket in buckets
            for key in keys
        ) / 1000.0

    solar = total("solar_energy_exported")
    battery_charged = total(
        "battery_energy_imported_from_grid",
        "battery_energy_imported_from_solar",
        "battery_energy_imported_from_generator",
    )
    battery_discharged = total("battery_energy_exported")
    grid_imported = total("grid_energy_imported")
    grid_exported = total(
        "grid_energy_exported_from_solar",
        "grid_energy_exported_from_battery",
        "grid_energy_exported_from_generator",
    )
    # Home consumption = everything delivered to the home from each source.
    home = total(
        "consumer_energy_imported_from_grid",
        "consumer_energy_imported_from_solar",
        "consumer_energy_imported_from_battery",
        "consumer_energy_imported_from_generator",
    )
    self_powered = (
        round(max(0.0, min(1.0, (home - grid_imported) / home)) * 100, 1)
        if home > 0
        else 0.0
    )
    return {
        "solar_kwh": round(solar, 2),
        "home_kwh": round(home, 2),
        "grid_imported_kwh": round(grid_imported, 2),
        "grid_exported_kwh": round(grid_exported, 2),
        "battery_charged_kwh": round(battery_charged, 2),
        "battery_discharged_kwh": round(battery_discharged, 2),
        "self_powered_pct": self_powered,
    }


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

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.access_token:
            raise RuntimeError("Tesla access token is missing")
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        url = f"{self.settings.api_base_url.rstrip('/')}{path}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=headers, params=params)
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

    async def calendar_history(
        self,
        energy_site_id: int,
        kind: str = "energy",
        period: str = "day",
        time_zone: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"kind": kind, "period": period}
        if time_zone:
            params["time_zone"] = time_zone
        return await self.get(
            f"/api/1/energy_sites/{energy_site_id}/calendar_history", params
        )


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

