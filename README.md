# Meron

Self-hosted personal training dashboard. Brings together Strava activity history, FIT files, and strength-training logs into one place — without handing your data to a third party.

Live public preview at <https://meron.gordongouger.com> (Overview tab; deeper tabs are gated by SSO).

## What it does

- **Routes on a map** — every ride and run plotted with elevation, heart rate, and pace overlays
- **Training trends** — CTL / ATL / TSB load curves, weekly volume, time-in-zone, distance histograms over time
- **Race predictions** — VDOT / Riegel-style time estimates from your recent races and tempo runs
- **Strength progression** — bench / squat / deadlift one-rep-max estimates pulled from FIT strength workouts
- **Heatmaps** — aggregate location heatmaps for runs, rides, and walks
- **Chat widget** — a small LLM-backed assistant that answers questions over your own ride and run data (read-only, opt-in)

The Overview tab is intentionally public-safe (counts, weekly sums, anonymized aggregates) so the project page on the main site can pull a live summary card without exposing the raw activity stream.

## Stack

- **Backend**: Flask + [Dash](https://dash.plotly.com/) + pandas + scipy + plotly, served by gunicorn
- **Storage**: SQLite (single DB file in `~/.meron/`)
- **Activity parsing**: [fitparse](https://github.com/dtcooper/python-fitparse) for FIT, [stravalib](https://github.com/stravalib/stravalib) for the Strava API
- **Auth**: HTTP forward-auth from an upstream reverse proxy (Authelia in production; a built-in Google OAuth flow for solo dev)
- **Maps**: Leaflet via a thin Dash bridge
- **Optional**: an MCP server (`mcp` extra) so ChatGPT and Claude can query your training data, and an OpenAI extra for the in-app chat widget

Memory tuning for small deployments lives in the [Dockerfile](Dockerfile) — gunicorn `--max-requests` recycling, `MALLOC_ARENA_MAX=2`, `MALLOC_TRIM_THRESHOLD_=100000`. Comfortable on a 2 GB VPS with 4 GB swap.

## Quick start

```sh
# Clone + install
git clone git@github.com:gogouger/meron.git
cd meron
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[web,api]" gunicorn

# Configure Strava OAuth — get the client id / secret from
# https://www.strava.com/settings/api, then:
cp .env.example .env
# fill in STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REDIRECT_URI

# Run
gunicorn --workers 1 --threads 4 --bind 0.0.0.0:8050 \
    strava_analytics.web.wsgi:app
# open http://localhost:8050
```

Or with Docker (uses the same env vars):

```sh
docker compose up -d
```

If you don't want to expose ports on your router, the `tunnel` profile starts a [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) sidecar — set `TUNNEL_TOKEN` in `.env` first, then `docker compose --profile tunnel up -d`.

## Architecture notes

- All state lives in one SQLite database (`~/.meron/meron.db` by default) plus a sidecar JSON index for the FIT files. No external services required.
- Strava tokens are encrypted at rest with a key derived from `MERON_SECRET_KEY` so a stolen DB file doesn't immediately expose your account.
- The Dash UI is sharded into pages under `strava_analytics/web/pages/` — each `page-` file is auto-registered. Adding a new page is one file.
- The "public Overview" pattern: Caddy's `@public` matcher exposes `/`, `/login`, `/api/public/*`, and Dash plumbing without `forward_auth`; everything else requires a session. See [infra/Caddyfile](https://github.com/gogouger/infra) for the production wiring.

## License

[MIT](LICENSE). Borrow it freely, ship your own variant. Personal training data is yours alone — none of it is in this repo.

## Author

[Gordon Gouger](https://www.linkedin.com/in/gordon-gouger/) — built to scratch my own itch with running + lifting trends.
