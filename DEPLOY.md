# LibreTutor Deployment

<p align="center">
  <strong>Run LibreTutor on your own server with Docker Compose, PostgreSQL, and Caddy.</strong>
</p>

<p align="center">
  <a href="README.md">README</a>
  ·
  <a href="DEPLOY.zh-CN.md">中文部署指南</a>
</p>

This guide describes the recommended self-hosted production setup. It runs three services:

| Service | Purpose |
| --- | --- |
| `caddy` | Public HTTPS entrypoint, automatic TLS, reverse proxy |
| `app` | FastAPI API plus the built React frontend |
| `db` | PostgreSQL 16 with pgvector |

The public origin is a single domain:

```text
https://learn.example.com/           -> LibreTutor app
https://learn.example.com/api/health -> API health check
```

## Requirements

- A Linux server with a public IP address
- A domain name pointing to that server
- Ports `80` and `443` open in both the cloud security group and host firewall
- Docker Engine and Docker Compose plugin
- An OpenAI-compatible or Anthropic-compatible chat API key
- Optional embedding API key for stronger semantic retrieval

LibreTutor has no built-in login. If your domain is reachable from the internet, protect it with a firewall, VPN, Caddy `basic_auth`, an OAuth proxy, or mTLS.

## 1. Install Docker

On Debian or Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Verify:

```bash
docker --version
docker compose version
```

Optional non-root Docker access:

```bash
sudo usermod -aG docker $USER
```

Log out and back in after changing the group.

## 2. Clone LibreTutor

```bash
git clone git@github.com:Deriicc/LibreTutor.git
cd LibreTutor
```

Use your own fork URL if you deploy from a fork.

## 3. Configure the Environment

```bash
cp .env.example .env
```

Generate an encryption key:

```bash
python3 -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Edit `.env`:

```dotenv
DOMAIN=learn.example.com
POSTGRES_USER=app
POSTGRES_PASSWORD=replace-with-a-strong-url-safe-password
POSTGRES_DB=self_learning
ENCRYPTION_KEY=replace-with-the-generated-key
CORS_ORIGINS=["https://learn.example.com"]
```

Optional model defaults:

```dotenv
CHAT_BASE_URL=https://api.deepseek.com
CHAT_API_KEY=
CHAT_MODEL=deepseek-chat
CHAT_PROVIDER=openai

EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
```

You can leave model keys blank and enter them later in the LibreTutor Settings page.

## 4. Start the Stack

```bash
docker compose up -d --build
```

Watch the app logs:

```bash
docker compose logs -f app
```

The app container runs database migrations automatically before starting the server.

## 5. Verify

Open:

```text
https://learn.example.com/
```

Check:

```bash
curl https://learn.example.com/api/health
```

Expected response:

```json
{"status":"ok"}
```

Production API docs should be hidden:

```text
https://learn.example.com/docs -> 404
```

## 6. Configure Model Keys

Open the app, go to Settings, and fill in:

- chat provider
- base URL
- API key
- model name
- optional embedding provider settings

With `ENCRYPTION_KEY` set, these settings are encrypted at rest in PostgreSQL.

## Access Control

LibreTutor is a private single-user workspace. Do not publish it without an access boundary.

Recommended options:

| Option | Best for |
| --- | --- |
| Cloud firewall / security group | Personal server with fixed IP access |
| VPN or private network | Home lab or private team |
| Caddy `basic_auth` | Simple password gate |
| OAuth proxy | Shared deployments |
| mTLS | Strict private infrastructure |

The `app` service is not published to the host. Only Caddy can reach it inside the Compose network.

## Maintenance

Update:

```bash
git pull
docker compose up -d --build
```

View status:

```bash
docker compose ps
docker compose logs -f app
docker compose logs -f caddy
```

Restart:

```bash
docker compose restart app
```

Stop:

```bash
docker compose stop
```

## Backups

Back up PostgreSQL:

```bash
docker compose exec -T db pg_dump -U app self_learning > libretutor.sql
```

Back up uploaded source files:

```bash
docker compose exec -T app tar czf - -C /data uploads > uploads.tgz
```

Restore PostgreSQL into an empty database:

```bash
cat libretutor.sql | docker compose exec -T db psql -U app self_learning
```

## Troubleshooting

### Caddy cannot issue a certificate

- Confirm the domain has an A or AAAA record pointing to the server.
- Confirm ports `80` and `443` are open.
- Check Caddy logs:

```bash
docker compose logs caddy
```

### The app container keeps restarting

Check logs:

```bash
docker compose logs app
```

Common causes:

- invalid `CORS_ORIGINS` JSON
- missing `ENCRYPTION_KEY`
- weak or malformed database settings
- database health check not passing

### Chat says model settings are missing

Set chat settings in the app's Settings page, or prefill `CHAT_API_KEY`, `CHAT_BASE_URL`, `CHAT_MODEL`, and `CHAT_PROVIDER` in `.env`.

### Uploads fail

The default upload limit is 50 MB. Confirm the file is one of:

```text
.pdf
.epub
.md
.markdown
```

## Platform Deployments

`railway.toml` is included for Dockerfile-based Railway deploys. On platforms that already provide HTTPS and reverse proxying, Caddy is not required. You still need PostgreSQL with pgvector, `PRODUCTION=true`, `ENCRYPTION_KEY`, and exact `CORS_ORIGINS`.
