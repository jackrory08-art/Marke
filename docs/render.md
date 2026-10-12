# Deploying Marke on Render's free plan

This runs Marke at an `https://` URL with nothing on your own computer, and without paying. It comes
with real limits, so read "What you give up" first. Not tested on a live Render account from this
repository; if a step differs from what you see, trust Render's current UI and docs.

## What you give up

| Limit | What it means for Marke |
|---|---|
| **No persistent disk** | The database lives in `/tmp` and is wiped on every restart or redeploy. Your login is re-created automatically from the bootstrap variables. AI verdicts, opportunity history, audit log and Settings changes reset. |
| **Sleeps after 15 minutes without traffic** | A sleeping service stops scanning. The fix below is a free pinger that visits it every 5 minutes. |
| **750 free hours a month, shared** | One always-on service uses about 720 of them, so keep this the only free service in the workspace. |
| **Small instance (512 MB)** | Fine for the simulation demo. Real mode loads thousands of markets and may run out of memory; watch the logs. |
| **Card may be required** | Sources conflict on whether Docker web services need a card on file. Render will tell you at sign-up. |

After a restart the AI re-verifies pairs, which uses your Gemini free-tier calls (400 a day by default).

## 1. Deploy

1. Sign up at render.com with GitHub.
2. **New → Blueprint**, pick `jackrory08-art/Marke`. Render reads `render.yaml` and proposes a free
   Docker web service called `marke`.
3. When asked for the secret values, enter:
   - `MARKE_BOOTSTRAP_USER`: the username you want (for example `owner`)
   - `MARKE_BOOTSTRAP_PASSWORD`: a long password (12+ characters)
   - `GEMINI_API_KEY`: your Google AI Studio key (optional; without it pairs stay unverified)
4. Apply. The first build takes a few minutes. Your URL is `https://marke-xxxx.onrender.com`.

Render announces its hostname to the app, so no host setup is needed. **Keep the bootstrap variables
set**: with no persistent disk the account is re-created from them on every start, and it only ever
happens when there are no users.

## 2. Stop it sleeping

1. Create a free account at uptimerobot.com.
2. **Add monitor → HTTP(s)**, URL `https://marke-xxxx.onrender.com/healthz`, interval 5 minutes.

`/healthz` answers both GET and HEAD, which is what free monitors send. Pings count as traffic and keep
the service awake.

## 3. Sign in

Open your URL, sign in with the bootstrap username and password.

## Try the demo data first

To check the UI with fake data before real markets, set these in `config.yaml`, commit, and let Render
redeploy:

```yaml
mode:
  data_mode: simulation
ai:
  provider: mock
trading:
  markets: ["sim-market-1", "sim-market-2"]
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| 400 "Invalid host header" | Using a custom domain. Add it to the `MARKE_ALLOWED_HOSTS` variable |
| Logged out every so often | The service restarted (new deploy, crash, or out of memory), which resets the database. Sign in again |
| Service slow on first visit | It was asleep; check the UptimeRobot monitor is running |
| Killed / out-of-memory in logs | Real mode is too large for 512 MB. Use simulation, or a paid instance |
| Pairs stay "Unverified" | No `GEMINI_API_KEY`, or the daily budget is used (Settings shows usage) |
