# Home Energy Dashboard — Tesla Powerwall + Solar + PG&E NBT

## Project goal
Build a small, initially read-only dashboard for our home Tesla solar + Powerwall system that makes the economics of PG&E's Net Billing Tariff (NBT) easier to understand than the Tesla app alone.

The dashboard should show live energy flow, daily totals, and—most importantly—estimate the dollar value of grid imports/exports by time of day. A later phase may recommend or automate EV charging to consume low-value excess solar while preserving battery energy for high-value evening exports.

## Home energy system
- Solar array: **11.76 kW DC**
- Panels: **28 × Tesla TSP-420**
- Inverter: **Tesla Powerwall 3, 11.5 kW effective inverter nameplate**
- Battery: **1 × Powerwall 3, 13.5 kWh / 11.5 kW**
- Utility: **PG&E**
- Community generation provider: **Central Coast Community Energy (3CE)**
- PG&E solar tariff: **NBT / Solar Billing Plan**
- PTO granted: **July 23, 2026**
- Tesla app rate-plan selection: **E-ELEC-NEM3-2026**
- Powerwall operating mode: currently **Savings**
- Energy exports: **Everything** (allows Powerwall energy to be exported when valuable)
- Backup reserve: **20%**
- EVs are generally home during the day, making daytime solar charging practical.

## Observed system behavior
Before PTO, the system could not export. With the Powerwall full, Tesla curtailed solar production to approximately match home load.

After PTO/export was enabled, normal behavior was confirmed. Example midday observation:
- Solar: 7.9 kW
- Home: 0.4 kW
- Powerwall: 100%, 0 kW
- Grid export: 7.5 kW

On a strong production day the system generated **63.6 kWh**.

Savings mode + `Energy Exports: Everything` also performs battery arbitrage. Example at ~7:20 PM:
- Solar: 0.2 kW
- Home: 1.0 kW
- Powerwall discharge: 10.4 kW
- Grid export: 9.6 kW
- Powerwall SOC: 70%
- Tesla app reported export compensation of **115¢/kWh ($1.15/kWh)** and explicitly said the Powerwall was exporting to maximize energy value.

This is a key use case for the dashboard: midday NBT exports may be worth only a few cents/kWh while some evening periods can be dramatically more valuable.

## EV charging observations
We experimented with manually adjusting a car's Level 2 charging current to absorb excess solar:
- 12 A ≈ 2.9 kW @ 240 V
- 24 A ≈ 5.8 kW
- 26 A ≈ 6.2 kW
- 28 A ≈ 6.7 kW
- 32 A ≈ 7.7 kW

A useful starting range on sunny days has been around **24–26 A**, adjusted according to live solar surplus and household load.

Desired future recommendation logic: when export compensation is low and sufficient battery energy is available for upcoming high-value periods, recommend an EV charging amperage that keeps grid import near zero.

## Tesla Fleet API setup
A Tesla Fleet API developer application has been created and **approved**.

OAuth grant type selected:
- **Authorization Code and Machine-to-Machine**

Initial local development URLs:
- Allowed Origin: `http://localhost:8000`
- Allowed Redirect URI: `http://localhost:8000/callback`

Initial API scope selected:
- **Energy Product Information only**

This is intentionally read-only for v1. Do **not** request Energy Product Commands or vehicle command permissions until the monitoring/dashboard functionality is working and there is a specific need.

Do not commit Tesla client secrets, OAuth tokens, private keys, account identifiers, or other credentials to the repository. Use environment variables / `.env`, and ensure `.env` is in `.gitignore`.

## Relevant Tesla Fleet API data
The Energy Product Information scope should be used to retrieve available energy-site information such as:
- Live/site status
- Solar production
- Home consumption
- Grid import/export
- Powerwall state of charge
- Battery charge/discharge
- Energy-flow history
- Time-of-use/rate information where exposed
- Tariff / savings forecast information where exposed

Prefer official Tesla Fleet API endpoints over undocumented local Powerwall APIs for the first version.

## V1 dashboard
A simple local web dashboard could show:

### Live
- Solar kW
- Home kW
- Powerwall SOC %
- Powerwall charge/discharge kW
- Grid import/export kW

### Today
- Solar generated (kWh)
- Home consumption (kWh)
- Grid imported (kWh)
- Grid exported (kWh)
- Battery charged/discharged (kWh), if available
- Self-powered percentage

### Economics
- Estimated import cost today
- Estimated export credits today
- Net electricity value today
- Current import rate ($/kWh)
- Current export compensation ($/kWh)
- Upcoming high-value export windows

Example UI:

```text
LIVE
Solar 8.4 kW · Home 1.1 kW · Powerwall 96% · Export 7.3 kW

TODAY
Generated 47.8 kWh · Exported 29.6 kWh · Imported 0.4 kWh

VALUE
Export credits $5.82 · Grid purchases $0.11 · Net +$5.71

NEXT
7–8 PM export: $1.15/kWh
Powerwall target before 7 PM: ≥75%

EV
Excess solar available: 5.9 kW
Suggested charge rate: ~24 A
```

## V2 ideas
After v1 is reliable:
1. Add PG&E/NBT export-compensation schedules so historical and current exports can be valued accurately.
2. Add 3CE generation/import costs where appropriate.
3. Forecast solar generation and compare it with expected household demand.
4. Recommend EV charging windows/amperage based on:
   - current excess solar
   - Powerwall SOC
   - expected solar later in the day
   - upcoming NBT export value
   - EV energy needed
5. Optionally add Tesla vehicle charging control if a Tesla vehicle is involved and appropriate scopes are granted.
6. Investigate control options for the Ford Mustang Mach-E / EVSE; initially recommendations can simply say, e.g., `Set Mach-E to 24 A`.
7. Only after careful testing, consider adding **Energy Product Commands** for Powerwall automation.

## Optimization philosophy
The goal is **not simply to maximize self-consumption**. Under NBT, the economically optimal behavior can be:

1. Power home loads from solar.
2. Maintain enough Powerwall energy to cover expensive household periods and/or exploit high-value export windows.
3. Charge EVs from otherwise low-value excess midday solar.
4. Export remaining solar.
5. Allow Powerwall export during unusually valuable NBT periods when financially advantageous.

In other words, a solar kWh exported at ~$0.05–$0.10 is very different from a Powerwall kWh exported at ~$1.15. The dashboard should make that opportunity cost visible.

## Suggested first implementation milestone
1. Create a small Python project.
2. Store credentials in environment variables.
3. Complete Tesla OAuth locally.
4. Discover the user's Energy site ID.
5. Make one read-only live-status request.
6. Print normalized values for solar, home, grid, battery power, and SOC.
7. Persist samples locally (SQLite is sufficient initially).
8. Add a minimal local dashboard (FastAPI + simple HTML/JS is sufficient; avoid overengineering).
9. Add daily energy-history retrieval.
10. Only then add PG&E/NBT dollar calculations.

## Local development

The first read-only vertical slice is scaffolded. It supports Tesla OAuth,
discovers the first energy site returned by `/api/1/products`, fetches
`live_status`, normalizes watts to kW, stores each sample in SQLite, and shows
the values in a minimal local dashboard.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
```

Add the Tesla application's client ID and client secret to `.env`. The default
redirect URI is `http://localhost:8000/callback`, matching the developer app
configuration described above. Then run:

```bash
.venv/bin/uvicorn home_energy_dashboard.app:app --reload
```

Open `http://localhost:8000`, choose **Connect Tesla**, authorize the requested
read-only `energy_device_data` scope, and refresh the live data. OAuth tokens
and samples are stored in the ignored local `energy.sqlite3` database.

Before labeling signed grid power as import/export or battery power as
charge/discharge, compare a live response with the Tesla app and document the
observed sign convention.

Run the current checks with:

```bash
.venv/bin/python -m pytest
```

## Security / safety
- Start read-only.
- Never expose Tesla credentials client-side.
- Never commit secrets or OAuth tokens.
- Treat API-returned signs/directions for grid and battery power carefully; normalize them once and test against the Tesla app.
- Do not automate Powerwall reserve/mode/export settings until read-only monitoring has been validated over multiple days.
