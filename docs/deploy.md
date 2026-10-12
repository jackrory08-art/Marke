# Deploying Marke

Marke is a single process (bot + dashboard) with a database. It is meant for one operator. Keep it on
loopback, or behind an HTTPS reverse proxy.

## 1. Choose how it listens

| Setup | `server.host` | `cookie_secure` | Notes |
|---|---|---|---|
| Same machine, browser on `localhost` | `127.0.0.1` (default) | `true` | Chrome and Firefox accept `Secure` cookies on `http://localhost` and `http://127.0.0.1`. Safari may not; use the proxy setup below. |
| Behind an HTTPS reverse proxy | `127.0.0.1` | `true` | Recommended for anything remote. |
| Docker | `0.0.0.0` inside the container | `true` | Compose publishes `127.0.0.1:8000` only. |
| Plain HTTP on a LAN | an interface address | `false` | Sessions travel unencrypted. Marke logs a warning. Avoid. |

Never publish the port on a public interface without TLS.

## 2. Settings for a proxy

```yaml
server:
  host: "127.0.0.1"
  port: 8000
  cookie_secure: true
  hsts: true                                   # once the site is HTTPS-only
  allowed_hosts: ["marke.example.com"]         # the Host header the proxy forwards
  allowed_origins: []                          # only add origins you control
```

`allowed_hosts` must match the public hostname or requests get `400 Invalid host header`. The
proxy must pass the original `Host` header and upgrade WebSocket connections on `/ws`.

### Caddy

```caddyfile
marke.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Caddy gets a certificate, forwards `Host` and proxies WebSockets without extra configuration.

### nginx

```nginx
server {
    listen 443 ssl http2;
    server_name marke.example.com;
    ssl_certificate     /etc/letsencrypt/live/marke.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/marke.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 120s;
    }
}
map $http_upgrade $connection_upgrade { default upgrade; '' close; }
```

Per-IP login throttling uses the connection's address. Behind a proxy that is the proxy's address,
so all users share one limit. This is fine for a single operator; the per-account lockout still applies.

## 3. Create the first user

```bash
python -m app.create_user --username owner
# Docker:
docker compose run --rm app python -m app.create_user --username owner
```

Passwords need at least 12 characters. A second user needs `--add`.

## 4. Environment

Copy `.env.example` to `.env`:

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | AI verifier and analyst. Without it pairs stay unverified. |
| `DATABASE_URL` | Defaults to `sqlite:///data/marke.db`. Postgres: `postgresql+psycopg://user:pass@host/db` (install `psycopg[binary]`; the test suite runs on SQLite only). |
| `MARKE_SESSION_SECRET` | Optional. If set, session tokens are stored as HMAC-SHA256(secret, token). Changing it signs everyone out. |
| `POLYMARKET_*` | Not needed for read-only dry-run use. |

## 5. Database and backups

Migrations run at startup (`database.auto_migrate: true`). To run them by hand:
`alembic upgrade head` (uses `DATABASE_URL`). With SQLite, back up the `data/` directory (or the
`marke-data` volume) while the app is stopped, or use `sqlite3 marke.db ".backup backup.db"`.

## 6. Operations

- **Health check:** `GET /healthz` returns `{"ok": true}`.
- **AI budget:** Settings shows calls and cost used today (UTC day). The budget survives restarts.
- **Audit log:** sign-ins, lockouts, logouts, user creation and setting changes appear under Logs and audit.
- **Logs:** the bot log is also in `logs/` (a container-local path in Docker).
- **Upgrades:** pull, rebuild, restart. Migrations are applied automatically.

## 7. Limits

This is an advisory tool. It does not place orders, live trading is disabled, and PredictIt data is
licensed for non-commercial use only.
