# GensokyoGeoGuesser Neo

A Touhou location-guessing game: identify a scene, place a guess on the Gensokyo map,
and compare results across rounds. [Play the deployed game](https://ggg-neo.arthas.org/lobby).

## Development and deployment

`dev` is the active development branch and the branch currently deployed on this
server. The maintained application lives at the repository root; `ref/` contains
the archived original implementation. Develop against `dev`, validate changes,
and update `main` explicitly when promoting a release.

The current checkout and service working directory are:

```text
/home/priv/apps/GensokyoGeoGuesser
```

The `ggg-neo` systemd service runs the Flask application through one Gunicorn worker
on `127.0.0.1:20811`. Nginx provides HTTPS and HTTP/2 at
`ggg-neo.arthas.org`, serves static assets directly, and proxies API and event requests.
See the [deployment guide](docs/deploy/README.md) for installation, updates, TLS,
and service management, and the [service unit](docs/deploy/ggg-neo.service) for the
installed working directory and launch command.

## Gameplay

- **Play Solo** opens a private one-player lobby. Configure rounds, difficulty,
  and scoring, then start.
- **Join** creates or joins a multiplayer room; an empty room ID uses quick matching.
  Hosts configure the game, and **Observe** joins as a spectator.
- Scoring modes and their parameters are defined in `config.yaml`; the lobby offers
  the configured modes. The supplied modes score by ranking or distance.
- The map supports mouse-wheel zoom and dragging, Safari trackpad gestures, and
  touchscreen pinch and pan. Reference maps and upcoming question images prefetch
  at low priority after current resources are ready.

## Local setup

The server uses Ubuntu 24.04, Python 3.12, and Node.js 18. Install Python's `venv`
support and npm before running the installer.

```bash
git switch dev
git pull --ff-only origin dev
./install.sh
.venv/bin/python app.py --host 127.0.0.1 --port 5000
```

Open `http://127.0.0.1:5000/lobby`. The installer creates `.venv/`, installs Python
and frontend dependencies, copies data assets into `static/`, builds the frontend,
and checks question images and locations. It uses an Aliyun PyPI mirror by default;
set `PIP_INDEX_URL` to use another index.

Keep the production service on port `20811`; use a different port for development.
Changes to the frontend require another build, or run the Vite development server
alongside the backend on port `5000`:

```bash
npm --prefix frontend run dev
```

Vite's local URL is `http://127.0.0.1:5173`; it proxies API and event traffic to the
backend. Application settings are in [config.yaml](config.yaml).

## Validation

Install pytest in the virtual environment for development checks:

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest tests -q
node --test tests/*.mjs
npm --prefix frontend run build
.venv/bin/python scripts/verify_data.py
```

Keep browser and load tests memory-limited on the deployment host. The application
uses in-memory room state, so production must use **one worker**; restarting it
ends active games. Its 32 threads admit up to 24 event streams, reserving capacity
for API requests. Other clients continue through state polling.

## Connection behavior

Game and lobby event streams send one-second heartbeats. Clients reconcile state
every two seconds, use two-second request deadlines, and resynchronize after a
connection interruption or browser resume. Presence leases allow a 60-second
reconnect grace period. Game actions use acknowledgements, duplicate protection,
and round/sequence checks; Submit waits for the latest guess to be acknowledged.

These settings target less than five seconds of stale state for a foreground
client that can reach the server. They cannot bound latency while a browser is
suspended or offline. Large source maps are retained at their intended resolution;
prefetch is deferred, serialized, and interrupted for urgent actions. Completed
map prefetches use a one-day browser Cache Storage entry shared by the lobby and
game; unavailable storage falls back to normal image loading. Game synchronization
starts before the map download, and waiting-room configuration keeps prefetch active.

## Repository layout

| Path | Purpose |
| --- | --- |
| `app.py` | Flask entry point and production application factory |
| `neo/` | Game engine, lobby, scoring, state, and event streams |
| `frontend/` | Vite frontend, map controls, and synchronization |
| `data/` | Question sheets, locations, source images, and maps |
| `scripts/` | Asset copying and dataset verification |
| `tests/` | Python tests and dependency-free JavaScript tests |
| `docs/` | Design notes and deployment instructions |
| `ref/` | Archived original application |

## HTTPS maintenance

The VPS provider blocks public HTTP, so certificates use **DNS-01 validation**.
DNS is managed in Cloudflare. The current certificate expires **January 29, 2027**.
Manual TXT-record validation must be repeated before expiry; the Certbot timer
cannot renew a manual certificate unattended. Follow the
[DNS-01 instructions](docs/deploy/README.md#4-https-with-manual-dns-01-validation)
when renewing, then reload Nginx.

We acknowledge the MC幻想郷 circle for sharing the Gensokyo map.
