# Self-Learning System

AI tutoring system. You upload a textbook (PDF or Markdown), the backend builds a fixed course tree, and you study each KnowledgePoint through Socratic dialogue, assessment, tailored exercises, grading, retry, and a teacher diary.

This is the **single-user, self-hosted** edition: clone it, set your API key on the in-app Settings page, and use it. No accounts, no login, no admin panel.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI + async SQLAlchemy + PostgreSQL 16 + pgvector |
| Frontend | React 18 + TypeScript + Vite (`frontend/`, port 5173) |
| LLM | OpenAI-compatible chat settings from the in-app Settings page |
| Embeddings | OpenAI-compatible embedding settings; hash embedding fallback if absent |
| Parsing | PyMuPDF for PDF, Markdown virtual pages for `.md` / `.markdown` |

## Prerequisites

- Ubuntu / WSL2
- PostgreSQL 16 + pgvector
- Python 3.11+
- Node 20+
- An OpenAI-compatible chat API key
- Optional embedding API key for semantic retrieval

## Setup

### 1. Postgres + pgvector

```bash
sudo apt-get update
sudo apt-get install -y postgresql-16 postgresql-16-pgvector
sudo service postgresql start

sudo -u postgres psql -c "CREATE USER app WITH PASSWORD 'app';"
sudo -u postgres psql -c "CREATE DATABASE self_learning OWNER app;"
sudo -u postgres psql -d self_learning -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env`:

```env
DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/self_learning
CORS_ORIGINS=["http://localhost:5173"]

# Dev default: false. In production this hides docs and requires ENCRYPTION_KEY.
PRODUCTION=false
ENCRYPTION_KEY=

# Optional app-level defaults. You normally set these on the in-app Settings
# page instead; filling them here just pre-seeds the defaults.
CHAT_API_KEY=
CHAT_BASE_URL=https://api.deepseek.com
CHAT_MODEL=deepseek-chat
CHAT_PROVIDER=openai

# Optional embedding defaults. Missing embedding config falls back to local
# deterministic hash embeddings.
EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
```

Run migrations:

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
```

### 3. Frontend

```bash
cd frontend
npm install
```

## Dev Server

```bash
./start.sh          # start Postgres + backend + frontend
./start.sh stop     # stop backend + frontend
./start.sh logs     # tail logs
./start.sh status   # show processes and endpoint status
```

Endpoints:

- Backend: `http://localhost:8000`
- App: `http://localhost:5173`
- Health: `curl http://localhost:8000/api/health`

## Configuring your API key

Open the app and go to **设置 (Settings)**. Enter your OpenAI-compatible chat
key/model (and optionally an embedding key) and save. The keys are stored in a
single `AppSettings` row, encrypted at rest when `ENCRYPTION_KEY` is set.

## Directory Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── chat/           SSE chat routes + Socratic prompt assembly
│   │   ├── courses/        Upload, tree builder, embedding/RAG, diary inputs
│   │   ├── kp/             Material, assessment, exercise, grading, diary flow
│   │   ├── models/         SQLAlchemy ORM models
│   │   ├── prompts/        Prompt files
│   │   ├── settings_router.py
│   │   ├── user_llm.py
│   │   └── crypto.py       EncryptedJSONB for the API settings blob
│   ├── alembic/            Migrations
│   └── tests/
├── frontend/
│   └── src/                App
├── docs/adr/               Architecture decisions
└── start.sh
```

## Architecture

### Domain Model

```text
Course -> Chapter -> Section -> KnowledgePoint
```

`KnowledgePoint` is the learning unit. It owns status (`untouched` / `in_progress` / `passed`) and participates in the full learning loop.

Two synthetic read-only KPs are injected around the body tree:

- `全书导读` (`boundary.kind = "overview"`)
- `全书总结` (`boundary.kind = "summary"`)

They can be discussed with the teacher, but they cannot be assessed, exercised, submitted, advanced, or passed. They are excluded from course progress and chapter/section rollup.

### Attempts

Retry is modeled as `KnowledgePoint.current_attempt`.

Attempt-scoped records:

- `Message(kp_id, attempt)`
- `KPAssessment(kp_id, attempt)`
- `KPExerciseSet(kp_id, attempt)`
- `Submission.attempt`
- `TeacherDiaryEntry(kp_id, attempt)`

Chat routes capture `current_attempt` once when the user sends or opens a dialogue. The assistant reply is written later after SSE streaming completes, but it keeps the captured attempt so a concurrent retry cannot split one turn across attempts.

### Material vs Exercise Set

`KPMaterial` is stable per KP:

- `layer3_prompt`
- `keyphrases`
- `knowledge_checklist`

It is generated from the textbook and reused across attempts.

`KPExerciseSet` is per attempt. It is generated after `KPAssessment`, using:

- material checklist + keyphrases
- assessment `covered` + `partial` concepts
- assessment suggested `difficulty` + `count`

Weakness review injection was removed. Weakness rows are still recorded for diary/context, but they do not feed later exercise generation.

### Prompt Stack

Every chat turn builds one system prompt:

| Layer | Content | Source |
|-------|---------|--------|
| Layer 1 | Socratic teaching rules | `prompts/socratic_layer1.md` |
| Layer 2 | Live Persona: scene, learner context, few-shots | current `TeacherConfig` |
| Layer 3 | KP position, keyphrases, checklist, RAG chunks | `KPMaterial` + retrieval |

Persona is live, not frozen. Editing `TeacherConfig` affects the next dialogue turn and the next diary entry. Old messages and old diary pages are not rewritten.

### Retrieval

At course build, the source file is chunked and indexed into `document_chunks`.

At chat time:

- KP with a page range -> fetch chunks overlapping that range in reading order.
- KP without a page range -> semantic top-k search with a query anchored by KP title, keyphrases, and the user message.

Synthetic overview/summary KPs have no page range, so they use whole-book semantic retrieval.

### Learning Lifecycle

1. You upload PDF or Markdown.
2. Builder creates the fixed 4-level tree, partitions front/back matter, injects overview/summary KPs, indexes chunks, and prewarms `KPMaterial`.
3. You open a KP. Chat shows only the current attempt's messages. The frontend buffers SSE deltas and flushes at most once per animation frame.
4. You request assessment. `KPAssessment` evaluates the current attempt's chat history against `KPMaterial.knowledge_checklist`.
5. You open exercises. `POST /exercise-set` generates or returns the current attempt's `KPExerciseSet`; `GET /content` is read-only for the current cached set.
6. You submit answers. Grading runs async; MCQ is deterministically scored, short answers are LLM-scored, and the overall score is weighted.
7. `advance(next)` marks the KP passed. `advance(retry)` bumps `current_attempt`. Either action writes a `TeacherDiaryEntry` for the attempt that just ended if that attempt had chat or a submission.

### Teacher Diary

`TeacherDiaryEntry` replaced the old learning report page. It is a first-person, Persona-authored diary page for one `(kp_id, attempt)`. Structured facts such as progress, grades, weaknesses, and assessment output are inputs to the diarist LLM; the UI presents diary prose, not a dashboard.

`courses.report._compute_progress` feeds the diary. It excludes synthetic KPs from completion counts and groups study time by `(kp_id, attempt)` so a long gap between retry rounds is not counted as study time. Synthetic-KP chat time still counts as study time by product definition.

## Production

Read [DEPLOY.md](DEPLOY.md) before a public deploy, or [DEPLOY.server.md](DEPLOY.server.md) for the self-hosted Docker Compose + Caddy stack.

Production hardening:

- `PRODUCTION=true` hides `/docs`, `/redoc`, and `/openapi.json`.
- Wildcard CORS is rejected in production.
- The API settings blob is encrypted at rest with Fernet `ENCRYPTION_KEY`.

> This edition has **no authentication** — anyone who can reach the app's port can use it. Control reachability at the network layer (firewall, a reverse proxy with auth, or a private network) when self-hosting on the public internet.

## Running Tests

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
pytest
```

Tests use real Postgres + pgvector. LLM call sites are monkeypatched.
