from __future__ import annotations

import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import httpx

from .config import settings
from .storage import Storage
from .tesla import TeslaClient, authorization_url, normalize_live_status


app = FastAPI(title="Home Energy Dashboard")
storage = Storage(settings.database_path)
oauth_states: set[str] = set()


@app.on_event("startup")
def startup() -> None:
    storage.initialize()


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    configured = settings.oauth_ready
    connected = storage.load_tokens() is not None
    action = (
        '<a href="/login">Connect Tesla</a>'
        if configured and not connected
        else '<button onclick="loadLive()">Refresh live data</button>'
        if connected
        else "Copy .env.example to .env and add the Tesla app credentials."
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Home Energy</title>
<style>body{{font:18px system-ui;max-width:760px;margin:3rem auto;padding:0 1rem}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:1rem}}
.card{{padding:1rem;border:1px solid #ddd;border-radius:12px}}small{{color:#666}}</style></head>
<body><h1>Home Energy</h1><p>{action}</p><div id="status"></div>
<div class="cards" id="cards"></div><script>
async function loadLive(){{const s=document.querySelector('#status');s.textContent='Loading…';
try{{const r=await fetch('/api/live');const d=await r.json();if(!r.ok)throw Error(d.detail);
const labels={{solar_kw:'Solar',home_kw:'Home',grid_kw:'Grid',battery_kw:'Battery',battery_soc:'Powerwall'}};
document.querySelector('#cards').innerHTML=Object.entries(d.sample).map(([k,v])=>
`<div class="card"><small>${{labels[k]}}</small><br><strong>${{v.toFixed(1)}} ${{k==='battery_soc'?'%':'kW'}}</strong></div>`).join('');s.textContent='';}}
catch(e){{s.textContent=e.message}}}};</script></body></html>"""


@app.get("/login")
async def login() -> RedirectResponse:
    if not settings.oauth_ready:
        raise HTTPException(503, "Tesla credentials are not configured")
    state = secrets.token_urlsafe(32)
    oauth_states.add(state)
    return RedirectResponse(authorization_url(settings, state))


@app.get("/callback")
async def callback(code: str, state: str) -> RedirectResponse:
    if state not in oauth_states:
        raise HTTPException(400, "Invalid or expired OAuth state")
    oauth_states.remove(state)
    try:
        tokens = await TeslaClient(settings).exchange_code(code)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, "Tesla token exchange failed") from exc
    storage.save_tokens(tokens)
    return RedirectResponse("/")


@app.get("/api/live")
async def live() -> dict:
    tokens = storage.load_tokens()
    if not tokens:
        raise HTTPException(401, "Connect Tesla first")
    client = TeslaClient(settings, tokens.get("access_token"))
    try:
        sites = await client.energy_sites()
        if not sites:
            raise HTTPException(404, "No Tesla energy site was found")
        site_id = None
        raw = None
        for site in sites:
            candidate_id = int(site["energy_site_id"])
            candidate = await client.live_status(candidate_id)
            if any(
                field in candidate
                for field in (
                    "solar_power",
                    "load_power",
                    "battery_power",
                    "percentage_charged",
                )
            ):
                site_id = candidate_id
                raw = candidate
                break
        if site_id is None or raw is None:
            raise HTTPException(404, "No Tesla solar or Powerwall site was found")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, "Tesla API request failed") from exc
    sample = normalize_live_status(raw)
    storage.save_sample(site_id, sample)
    return {"energy_site_id": site_id, "sample": sample.as_dict()}

