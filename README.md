# LibreTutor

<p align="center">
  <strong>A self-hosted AI tutor for turning books and notes into guided lessons.</strong>
</p>

<p align="center">
  <a href="README.zh-CN.md">中文</a>
  ·
  <a href="DEPLOY.md">Deployment</a>
  ·
  <a href="DEPLOY.zh-CN.md">中文部署</a>
</p>

<p align="center">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-111827?style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="React" src="https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=111827">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL%20%2B%20pgvector-4169E1?style=flat-square&logo=postgresql&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white">
</p>

LibreTutor is a single-user, bring-your-own-key learning workspace. Upload a PDF, EPUB, or Markdown file; LibreTutor reads the structure, builds a lesson path, and guides you through each lesson with an AI tutor, dialogue-based assessment, tailored exercises, grading, and a reflective tutor journal.

It is designed for private study, independent reading, and serious self-learning. No hosted account layer, no platform lock-in.

## Why LibreTutor

Most AI learning tools stop at chat over documents. LibreTutor turns a source file into a study loop:

| Step | What happens |
| --- | --- |
| Upload | Add a PDF, EPUB, or Markdown source. |
| Structure | LibreTutor extracts or infers chapters, sections, and lessons. |
| Dialogue | A configurable AI tutor teaches through focused conversation. |
| Assessment | The current conversation is checked against the lesson goals. |
| Practice | Exercises are generated from what you covered and what you missed. |
| Reflection | The tutor writes a journal entry for the completed attempt. |

## Features

- **Private by default**: self-host it on your own server and use your own model keys.
- **Book-shaped learning**: keeps the original chapter and section structure instead of flattening a book into loose chunks.
- **Persona-aware tutor**: define the tutor's voice, relationship, and teaching style per course.
- **Streaming dialogue**: server-sent events keep long tutor replies responsive.
- **Retrieval grounded in the source**: pgvector-backed semantic search brings relevant passages into each lesson.
- **Assessment before practice**: exercises are tailored after LibreTutor has read the learning conversation.
- **Attempt-aware progress**: retries keep their own dialogue, exercises, grading, and journal entry.
- **One-container app image**: the production image serves both the React app and FastAPI API.

## Quick Start

For a public or semi-private server, use the Docker Compose stack:

```bash
git clone git@github.com:Deriicc/LibreTutor.git
cd LibreTutor
cp .env.example .env
```

Edit `.env`:

```dotenv
DOMAIN=learn.example.com
POSTGRES_PASSWORD=replace-with-a-strong-password
ENCRYPTION_KEY=replace-with-a-generated-key
CORS_ORIGINS=["https://learn.example.com"]
```

Generate an encryption key with:

```bash
python3 -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Start the stack:

```bash
docker compose up -d --build
```

Open:

```text
https://learn.example.com/
```

Read the full guide: [DEPLOY.md](DEPLOY.md).

## Local Development

LibreTutor expects PostgreSQL 16 with pgvector, Python 3.11+, and Node 20+.

```bash
sudo apt-get update
sudo apt-get install -y postgresql-16 postgresql-16-pgvector
sudo service postgresql start

sudo -u postgres psql -c "CREATE USER app WITH PASSWORD 'app';"
sudo -u postgres psql -c "CREATE DATABASE self_learning OWNER app;"
sudo -u postgres psql -d self_learning -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Create `backend/.env`:

```dotenv
DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/self_learning
CORS_ORIGINS=["http://localhost:5173"]
PRODUCTION=false
ENCRYPTION_KEY=

CHAT_BASE_URL=https://api.deepseek.com
CHAT_API_KEY=
CHAT_MODEL=deepseek-chat
CHAT_PROVIDER=openai

EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
```

Install dependencies and migrate:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head

cd ../frontend
npm install
```

Run the local app:

```bash
./start.sh
```

Local endpoints:

```text
App:     http://localhost:5173
API:     http://localhost:8000
Health:  http://localhost:8000/api/health
```

## Model Configuration

LibreTutor uses OpenAI-compatible chat settings by default and also supports Anthropic-compatible chat settings from the in-app Settings page.

Embeddings are optional. If you do not configure an embedding model, LibreTutor falls back to deterministic local hash embeddings so the app can still run; semantic retrieval quality improves when you provide a real embedding model.

## Architecture

```text
Source file
  -> Course map
  -> Lessons
  -> Tutor dialogue
  -> Assessment
  -> Exercises
  -> Grading
  -> Tutor journal
```

| Layer | Stack |
| --- | --- |
| Frontend | React 18, TypeScript, Vite |
| Backend | FastAPI, async SQLAlchemy, Alembic |
| Database | PostgreSQL 16, pgvector |
| Parsing | PyMuPDF for PDF and EPUB, Markdown virtual pages |
| LLM | User-configured chat and embedding providers |
| Production | Docker Compose, Caddy, one app image |

Code map:

```text
backend/app/
  chat/        tutor dialogue and prompt assembly
  courses/     upload, course map building, retrieval, reports
  kp/          lesson material, assessment, exercises, grading, journal
  models/      SQLAlchemy models
  prompts/     tutor, assessment, exercise, and journal prompts

frontend/src/
  routes/      app pages
  components/  shared UI
  api/         browser API clients
```

## Security Model

LibreTutor is intentionally single-user and has no built-in login screen. Anyone who can reach the app can use the configured model keys and read the stored courses.

For internet-facing deployments, put LibreTutor behind at least one of:

- a firewall or cloud security group limited to your IPs
- a VPN or private network
- Caddy `basic_auth`
- an OAuth proxy
- mTLS

Production mode requires `ENCRYPTION_KEY` and encrypts the model settings stored in the database.

## Commands

```bash
# local development
./start.sh
./start.sh stop
./start.sh logs
./start.sh status

# production
docker compose up -d --build
docker compose logs -f app
docker compose ps

# backend tests
cd backend
source .venv/bin/activate
pytest
```

## Documentation

- [English deployment guide](DEPLOY.md)
- [中文部署指南](DEPLOY.zh-CN.md)
- [Architecture decisions](docs/adr)
- [Project context](CONTEXT.md)

## License

MIT License. See [LICENSE](LICENSE).
