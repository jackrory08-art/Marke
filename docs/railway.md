# Deploying Marke on Railway

Railway builds the repo's `Dockerfile` and gives you an `https://` URL. Nothing runs on your own
computer. You need a Railway account on a **paid plan** (Hobby is enough): the app needs a
persistent volume, which trial and free plans may not include.

This path has not been tested on a live Railway project from this repository. If a step differs from
what you see, trust Railway's current UI and docs.

## 1. Create the service

1. In Railway: **New Project → Deploy from GitHub repo**, and pick `jackrory08-art/Marke`.
   (Authorise Railway's GitHub app for the repo if it asks.)
2. Railway detects `railway.json` and the `Dockerfile`. The first build takes a few minutes.
   It may fail the health check until step 4 is done; that is expected.

## 2. Add a volume (keeps your data)

Service → **Settings → Volumes → New volume**, mount path **`/data`**.
Without this, the database (your login, verdicts, history) is wiped on every redeploy.

## 3. Generate a public URL

Service → **Settings → Networking → Generate Domain**. You get something like
`marke-production-1a2b.up.railway.app`. (A custom domain works too: add it here and follow
Railway's DNS instructions.)

## 4. Set variables

Service → **Variables**. Add:

| Variable | Value |
|---|---|
| `DATABASE_URL` | `sqlite:////data/marke.db` (four slashes) |
| `RAILWAY_RUN_UID` | `0` (volumes are root-owned; the container runs as a non-root user otherwise) |
| `MARKE_ALLOWED_HOSTS` | `marke-production-1a2b.up.railway.app,healthcheck.railway.app` (your real domain, plus Railway's health-check host) |
| `GEMINI_API_KEY` | Your Google AI Studio key (optional; without it every pair stays unverified) |
| `MARKE_BOOTSTRAP_USER` | The username you want, for example `owner` |
| `MARKE_BOOTSTRAP_PASSWORD` | A long password (12+ characters) |

Railway redeploys when you save. `PORT` is set by Railway and the app follows it.

## 5. Sign in, then remove the password variable

Open your Railway URL and sign in with the bootstrap username and password.

Then **delete `MARKE_BOOTSTRAP_PASSWORD`** from Variables. The account stays in the database. The
bootstrap only ever runs when there are no users, so it cannot add or reset accounts later, but there is
no reason to keep a password sitting in the environment.

## What to expect

- The dashboard starts in dry-run mode. Nothing here can place orders.
- With `data_mode: real` (the default in `config.yaml`) the first minutes are spent loading markets and
  matching pairs, so the Opportunities screen may be empty at first.
- To preview the UI with fake data, set `mode.data_mode: simulation` and `ai.provider: mock` in
  `config.yaml`, commit, and redeploy. Simulation mode also needs `trading.markets` ids if the server
  cannot reach Polymarket.
- Some regions are blocked by Polymarket or Kalshi. If market loading fails in the logs, try a different
  Railway region (Service → Settings → Deploy → Region).
- Settings you change in the UI (AI on/off, budgets) are saved in the volume and survive redeploys.
  Changes to `config.yaml` need a commit and redeploy.
- Login throttling counts everyone behind Railway's proxy as one address. That is fine for one person.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| "Invalid host header" or 400 on every page | `MARKE_ALLOWED_HOSTS` is missing or does not match the domain exactly |
| Deploy stays "unhealthy" | `healthcheck.railway.app` missing from `MARKE_ALLOWED_HOSTS` |
| `unable to open database file` in logs | No volume at `/data`, or `RAILWAY_RUN_UID=0` not set |
| Sign-in works but you are logged out on every reload | `DATABASE_URL` points outside the volume, so the DB resets on redeploy |
| No user exists | Bootstrap variables were not set before the first start, or the password is under 12 characters (check the logs). Set them and redeploy |
| Pairs stay "Unverified" | `GEMINI_API_KEY` missing, or the daily budget is used up (Settings shows usage) |
