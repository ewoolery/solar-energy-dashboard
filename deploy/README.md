# Deploying to the Raspberry Pi

The dashboard is a stateful, always-on service (it polls the Tesla API on an
interval and stores samples in SQLite), so it runs well on a small always-on
host like the `vestabridge` Pi rather than a serverless platform.

## One-command deploy

From the project root on your Mac:

```bash
./deploy/deploy.sh
```

This syncs the code to `ewoolery@192.168.7.34:/home/ewoolery/tesla-energy-dashboard`,
copies your local `.env` and `energy.sqlite3` (so the Pi inherits the existing
OAuth tokens — no re-authorization needed), enables the background sampler
(`SAMPLE_INTERVAL_SECONDS=600`), builds a venv, and installs + starts the
`tesla-energy-dashboard` systemd service listening on `0.0.0.0:8000`.

**API cost:** Tesla bills data requests at ~$0.002 each with a $10/month free
credit. The 10-minute poll interval (`600`) keeps usage inside that credit
(~4,400 requests/month ≈ free). Dropping to 60s would run ~$75+/month, so keep
the interval at 300s or higher unless your developer.tesla.com usage shows the
energy endpoints are cheaper for you. The dashboard also pauses its own polling
when the browser tab is hidden.

Open **http://192.168.7.34:8000** on any device on the home network.

Override the target with env vars if needed:
`PI_HOST=ewoolery@192.168.7.34 APP_DIR=/home/ewoolery/tesla-energy-dashboard ./deploy/deploy.sh`
(If you change `APP_DIR`, update the paths in `tesla-energy-dashboard.service` to match.)

## Managing the service on the Pi

```bash
sudo systemctl status tesla-energy-dashboard      # is it running?
journalctl -u tesla-energy-dashboard -f           # live logs
sudo systemctl restart tesla-energy-dashboard     # after a redeploy
```

Redeploying is just re-running `./deploy/deploy.sh` (it rsyncs and the service
auto-restarts on the next `systemctl restart`, or add one to the script).

## Notes

- **Tokens & re-auth:** the app refreshes the access token automatically using
  the long-lived refresh token, and refresh needs only the client ID/secret —
  not the OAuth redirect URI — so seeding `energy.sqlite3` keeps the Pi
  connected indefinitely. If the refresh chain ever fully breaks, re-run OAuth:
  SSH port-forward (`ssh -L 8000:localhost:8000 ewoolery@192.168.7.34`) and use
  the `localhost:8000/callback` redirect that is already registered, or add the
  Pi's URL as an allowed redirect URI in the Tesla developer app.
- **Access scope:** binds to `0.0.0.0` for LAN access. The dashboard is
  read-only and the data is non-sensitive, but it has no auth — keep it on the
  home network. For remote access, front it with the existing Cloudflare tunnel
  (add an ingress rule for a new subdomain → `http://localhost:8000`) instead of
  port-forwarding on the router.
- **Rates are estimates:** tune `src/home_energy_dashboard/rates.py` against your
  PG&E statement; they are not billed amounts.
