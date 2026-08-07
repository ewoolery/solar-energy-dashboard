from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
import httpx

from . import rates
from .config import settings
from .storage import Storage
from .tesla import (
    TeslaClient,
    authorization_url,
    is_expired,
    normalize_live_status,
    stamp_expiry,
    summarize_energy_history,
)


logger = logging.getLogger("home_energy_dashboard")

app = FastAPI(title="Home Energy Dashboard")
storage = Storage(settings.database_path)
oauth_states: set[str] = set()

# Discovered once, then reused so every request doesn't re-scan /products.
_site_id: int | None = None
_sampler_task: asyncio.Task | None = None


@app.on_event("startup")
async def startup() -> None:
    storage.initialize()
    global _sampler_task
    if settings.sample_interval_seconds > 0:
        _sampler_task = asyncio.create_task(_sampler_loop())
        logger.info("Background sampler every %ss", settings.sample_interval_seconds)


@app.on_event("shutdown")
async def shutdown() -> None:
    if _sampler_task:
        _sampler_task.cancel()


async def _sampler_loop() -> None:
    """Poll live status on an interval so history/economics accrue headless."""
    interval = settings.sample_interval_seconds
    while True:
        try:
            await _sample_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # never let one bad poll kill the loop
            logger.warning("Background sample failed: %s", exc)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise


# --- Auth helpers ------------------------------------------------------------
async def _refresh_tokens(tokens: dict[str, Any]) -> dict[str, Any] | None:
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return None
    new = await TeslaClient(settings).refresh(refresh_token)
    stamped = stamp_expiry(new, previous=tokens)
    storage.save_tokens(stamped)
    return stamped


async def _valid_tokens() -> dict[str, Any] | None:
    """Load tokens, transparently refreshing an expired access token."""
    tokens = storage.load_tokens()
    if not tokens:
        return None
    if is_expired(tokens):
        try:
            refreshed = await _refresh_tokens(tokens)
        except httpx.HTTPStatusError:
            refreshed = None
        return refreshed or tokens
    return tokens


async def _call(fn: Callable[[TeslaClient], Awaitable[Any]]) -> Any:
    """Run a Tesla API operation, refreshing + retrying once on a 401."""
    tokens = await _valid_tokens()
    if not tokens:
        raise HTTPException(401, "Connect Tesla first")
    client = TeslaClient(settings, tokens.get("access_token"))
    try:
        return await fn(client)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            try:
                refreshed = await _refresh_tokens(tokens)
            except httpx.HTTPStatusError:
                refreshed = None
            if refreshed:
                retry = TeslaClient(settings, refreshed.get("access_token"))
                try:
                    return await fn(retry)
                except httpx.HTTPStatusError as exc2:
                    raise HTTPException(
                        exc2.response.status_code, "Tesla API request failed"
                    ) from exc2
        raise HTTPException(exc.response.status_code, "Tesla API request failed") from exc


async def _resolve_site(client: TeslaClient) -> tuple[int, dict[str, Any]]:
    """Return (energy_site_id, live_status) for the first solar/Powerwall site."""
    global _site_id
    if _site_id is not None:
        return _site_id, await client.live_status(_site_id)
    sites = await client.energy_sites()
    if not sites:
        raise HTTPException(404, "No Tesla energy site was found")
    for site in sites:
        candidate = int(site["energy_site_id"])
        raw = await client.live_status(candidate)
        if any(
            field in raw
            for field in ("solar_power", "load_power", "battery_power", "percentage_charged")
        ):
            _site_id = candidate
            return candidate, raw
    raise HTTPException(404, "No Tesla solar or Powerwall site was found")


def _local_day_start_utc() -> str:
    zone = ZoneInfo(settings.timezone)
    now_local = datetime.now(zone)
    midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).isoformat()


# --- OAuth -------------------------------------------------------------------
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
    storage.save_tokens(stamp_expiry(tokens))
    return RedirectResponse("/")


# --- Data endpoints ----------------------------------------------------------
async def _sample_once() -> dict:
    """Fetch one live_status reading and persist it."""
    async def op(client: TeslaClient) -> dict:
        site_id, raw = await _resolve_site(client)
        sample = normalize_live_status(raw)
        storage.save_sample(site_id, sample)
        return {"energy_site_id": site_id, "sample": sample.as_dict()}

    return await _call(op)


@app.get("/api/live")
async def live() -> dict:
    return await _sample_once()


@app.get("/api/today")
async def today() -> dict:
    async def op(client: TeslaClient) -> dict:
        site_id, _ = await _resolve_site(client)
        history = await client.calendar_history(
            site_id, kind="energy", period="day", time_zone=settings.timezone
        )
        return {"energy_site_id": site_id, "totals": summarize_energy_history(history)}

    return await _call(op)


@app.get("/api/economics")
async def economics() -> dict:
    samples = storage.samples_since(_local_day_start_utc())
    result = rates.value_samples(samples, tz=settings.timezone)
    return {"samples_today": len(samples), "economics": result.as_dict()}


@app.get("/api/history")
async def history(limit: int = 240) -> dict:
    return {"samples": storage.recent_samples(max(1, min(limit, 1000)))}


# --- UI ----------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    configured = settings.oauth_ready
    connected = storage.load_tokens() is not None
    if configured and not connected:
        action = '<a class="cta" href="/login">Connect Tesla</a>'
    elif connected:
        action = '<button class="cta" onclick="loadAll()">Refresh now</button>'
    else:
        action = '<p class="hint">Copy <code>.env.example</code> to <code>.env</code> and add the Tesla app credentials.</p>'
    return _PAGE.replace("{{ACTION}}", action).replace(
        "{{CONNECTED}}", "true" if connected else "false"
    )


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Home Energy</title>
<style>
:root{
  --ink:#0A0A0A; --text:#F2F0EC; --dim:rgba(242,240,236,0.62); --faint:rgba(242,240,236,0.38);
  --raised:rgba(255,255,255,0.04); --raised-2:rgba(255,255,255,0.06); --border:rgba(255,255,255,0.08);
  --signal:#FF4725; --signal-bright:#FF5B3D;
  --display:"Space Grotesk","F37 Lineca",system-ui,sans-serif;
  --body:"Inter Tight","Aktiv Grotesk",system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,"SF Mono",Menlo,monospace;
  --ease:cubic-bezier(0.4,0,0.2,1);
}
*{box-sizing:border-box}
body{margin:0;background:var(--ink);color:var(--text);font-family:var(--body);
  font-size:18px;line-height:1.5;-webkit-font-smoothing:antialiased;
  padding:48px 24px 96px;}
.wrap{max-width:880px;margin:0 auto;}
header{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;
  gap:16px;margin-bottom:8px;}
h1{font-family:var(--display);font-size:48px;line-height:1.1;letter-spacing:-0.02em;
  font-weight:600;margin:0;}
.sub{color:var(--dim);margin:0 0 32px;font-size:16px;}
.cta{display:inline-flex;align-items:center;justify-content:center;line-height:1;
  background:var(--signal);color:var(--ink);font-family:var(--body);
  font-size:16px;font-weight:600;border:0;border-radius:9999px;
  /* Optical centering: the label has no descenders, so its ink sits high in
     the line box. Extra top padding lowers it to the pill's true center
     (measured: balances the cap-height ink within ~0.2px). */
  padding:16.5px 24px 11.5px;
  cursor:pointer;text-decoration:none;transition:background .12s var(--ease);}
.cta:hover{background:var(--signal-bright);}
.hint{color:var(--dim);} code{font-family:var(--mono);font-size:0.85em;color:var(--text);}
.section{margin-top:48px;}
.label{font-family:var(--mono);font-size:14px;letter-spacing:0.04em;text-transform:uppercase;
  color:var(--faint);margin:0 0 16px;}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px;}
.card{background:var(--raised);border-radius:16px;padding:24px;transition:background .24s var(--ease);}
.card:hover{background:var(--raised-2);}
.card .k{font-family:var(--mono);font-size:14px;letter-spacing:0.04em;text-transform:uppercase;
  color:var(--dim);margin-bottom:8px;}
.card .v{font-family:var(--display);font-size:36px;line-height:1.1;letter-spacing:-0.02em;font-weight:600;}
.card .u{font-size:16px;color:var(--dim);margin-left:4px;font-family:var(--body);}
.card .note{color:var(--faint);font-size:14px;margin-top:8px;font-family:var(--body);}
.accent{color:var(--signal);}
.status{color:var(--faint);font-size:14px;font-family:var(--mono);min-height:1.2em;}
.est{color:var(--faint);font-size:14px;margin-top:16px;font-style:italic;}
.err{color:var(--signal);}
@media (max-width:520px){h1{font-size:36px}body{padding:32px 16px 64px}}
</style></head>
<body><div class="wrap">
<header>
  <h1>Home Energy</h1>
  <div>{{ACTION}}</div>
</header>
<p class="sub" id="updated"></p>
<div class="status err" id="status"></div>

<section class="section" id="live-section" hidden>
  <p class="label">Live</p>
  <div class="cards" id="live"></div>
</section>

<section class="section" id="today-section" hidden>
  <p class="label">Today</p>
  <div class="cards" id="today"></div>
</section>

<section class="section" id="value-section" hidden>
  <p class="label">Value</p>
  <div class="cards" id="value"></div>
  <p class="est">Dollar figures are editable estimates (see rates.py), not billed amounts.</p>
</section>

<script>
const $ = (id) => document.getElementById(id);
const fmt = (n, d=1) => Number(n).toFixed(d);
const card = (k, v, u='', note='') =>
  `<div class="card"><div class="k">${k}</div><div class="v">${v}${u?`<span class="u">${u}</span>`:''}</div>${note?`<div class="note">${note}</div>`:''}</div>`;

function renderLive(d){
  const s = d.sample;
  // Sign convention: grid>0 import, <0 export; battery>0 discharge, <0 charge.
  const grid = s.grid_kw >= 0
    ? card('Grid', fmt(Math.abs(s.grid_kw)), 'kW', 'Importing')
    : card('Grid', fmt(Math.abs(s.grid_kw)), 'kW', '<span class="accent">Exporting</span>');
  let battState = 'Idle';
  if (s.battery_kw > 0.05) battState = 'Discharging';
  else if (s.battery_kw < -0.05) battState = 'Charging';
  const batt = card('Powerwall', fmt(s.battery_soc,0), '%',
    `${battState}${Math.abs(s.battery_kw)>0.05?` · ${fmt(Math.abs(s.battery_kw))} kW`:''}`);
  $('live').innerHTML =
    card('Solar', fmt(s.solar_kw), 'kW') +
    card('Home', fmt(s.home_kw), 'kW') +
    batt + grid;
  $('live-section').hidden = false;
}

function renderToday(t){
  $('today').innerHTML =
    card('Generated', fmt(t.solar_kwh), 'kWh') +
    card('Consumed', fmt(t.home_kwh), 'kWh') +
    card('Imported', fmt(t.grid_imported_kwh), 'kWh') +
    card('Exported', fmt(t.grid_exported_kwh), 'kWh') +
    card('Self-powered', fmt(t.self_powered_pct,0), '%');
  $('today-section').hidden = false;
}

function renderValue(e){
  const net = e.net_value;
  $('value').innerHTML =
    card('Export credits', '$'+fmt(e.export_credit,2)) +
    card('Grid purchases', '$'+fmt(e.import_cost,2)) +
    card('Net today', `<span class="accent">${net>=0?'+':'-'}$${fmt(Math.abs(net),2)}</span>`) +
    card('Import rate', '$'+fmt(e.current_import_rate,2), '/kWh', 'right now') +
    card('Export value', '$'+fmt(e.current_export_rate,2), '/kWh', 'right now');
  $('value-section').hidden = false;
}

async function getJSON(url){
  const r = await fetch(url);
  const d = await r.json();
  if(!r.ok) throw Error(d.detail || ('Request failed: '+url));
  return d;
}

async function loadAll(){
  $('status').textContent = '';
  try{
    const live = await getJSON('/api/live');
    renderLive(live);
    // Totals + economics are best-effort; a failure here shouldn't blank live.
    try{ renderToday((await getJSON('/api/today')).totals); }catch(e){}
    try{ renderValue((await getJSON('/api/economics')).economics); }catch(e){}
    $('updated').textContent = 'Updated ' + new Date().toLocaleTimeString();
  }catch(e){
    $('status').textContent = e.message;
  }
}

if({{CONNECTED}}){ loadAll(); setInterval(loadAll, 30000); }
</script>
</div></body></html>"""
