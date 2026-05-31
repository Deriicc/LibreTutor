# Production Deployment & Security Checklist

This is the **single-user, self-hosted** edition: there is no login, no
accounts, and no admin panel. The app is unauthenticated, so the most
important deploy decision is **who can reach it** (see §5). For the
turnkey Docker Compose + Caddy path, see [DEPLOY.server.md](DEPLOY.server.md);
this file is the generic manual checklist.

## 1. Secrets (do this first — manual)

- [ ] **Rotate the dev LLM keys.** A development `backend/.env` may have
      contained live `CHAT_API_KEY` / `EMBEDDING_API_KEY`. Revoke them in
      the provider console and issue new ones.
- [ ] Production keys (if any) live only in the server's `.env`, created
      from `backend/.env.production.example`. Never commit a filled
      `.env`; never bake it into a container image or build context.
- [ ] Dedicated Postgres role with a strong password — not `app:app`.

## 2. Environment

- [ ] `PRODUCTION=true` — hides `/docs`, `/redoc`, `/openapi.json` and
      makes `ENCRYPTION_KEY` mandatory.
- [ ] `CORS_ORIGINS` set to the exact HTTPS frontend origin(s) as a JSON
      list. A `"*"` origin makes the app refuse to boot under
      `PRODUCTION=true`.
- [ ] `DATABASE_URL` points at the production database.
- [ ] `ENCRYPTION_KEY` set to a generated Fernet key (encrypts the API
      keys you enter on the Settings page at rest). The app refuses to
      boot under `PRODUCTION=true` without it. Keep it stable and backed
      up — rotating it makes already-encrypted `api_settings` unreadable.
      Generate: `python -c "from cryptography.fernet import Fernet;
      print(Fernet.generate_key().decode())"`

## 3. TLS & reverse proxy

Terminate TLS at a reverse proxy (nginx / Caddy); never expose uvicorn
directly.

- [ ] Valid certificate; HTTP → HTTPS redirect.
- [ ] `Strict-Transport-Security` (HSTS) header.
- [ ] Security headers: `X-Content-Type-Options: nosniff`,
      `X-Frame-Options: DENY` (or a frame-ancestors CSP),
      a baseline `Content-Security-Policy`.
- [ ] Proxy forwards `X-Forwarded-For`. Run uvicorn with
      `--proxy-headers --forwarded-allow-ips="<proxy ip>"` so logs show
      the real client IP, not the proxy.
- [ ] Proxy-level request size / connection limits as defence in depth
      for the upload endpoints.

## 4. App server

- [ ] Run without `--reload`; use multiple workers, e.g.
      `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
      --proxy-headers`.
      Bind to `127.0.0.1` (proxy reaches it locally), not `0.0.0.0`.
- [ ] `pip install -r backend/requirements.txt`; run `alembic upgrade
      head` before starting.
- [ ] Build and serve the frontend: `frontend/` proxies `/api` to the
      backend origin.

## 5. Access control (no built-in auth)

This edition has **no authentication**. Anyone who can open the app can
read every course and use your configured API keys. Restrict reachability:

- [ ] Don't expose it nakedly on the public internet. Put it behind one
      of: a firewall / security group limited to your IPs, a VPN or
      private network, or a reverse proxy that adds auth (e.g. Caddy
      `basic_auth`, an OAuth proxy, or mTLS).
- [ ] Treat the configured LLM keys as spendable: whoever reaches the app
      can run up usage on them.

## 6. Verify after deploy

- [ ] `https://<domain>/docs` → 404 (docs disabled).
- [ ] `https://<domain>/api/health` → `{"status":"ok"}`.
- [ ] Opening `/` loads the app directly with no login redirect.
- [ ] `/admin` → 404 (no admin panel in this edition).
- [ ] A cross-origin browser request from an origin not in
      `CORS_ORIGINS` is blocked.
- [ ] The Settings page saves a key and `测试 (test)` succeeds.
