<div align="center">

<h1>LibreTutor</h1>

<p>
  <strong><i>A self-hosted AI tutor that turns books, notes,<br>and long-form documents into a guided learning path.</i></strong>
</p>

<p>
  <a href="#what-libretutor-does">Features</a>
  &nbsp;·&nbsp;
  <a href="#screenshots">Screenshots</a>
  &nbsp;·&nbsp;
  <a href="#self-hosted-deployment">Deploy</a>
  &nbsp;·&nbsp;
  <a href="README.zh-CN.md">简体中文</a>
</p>

<p>
  <img alt="License" src="https://img.shields.io/badge/License-MIT-111827?style=flat-square&labelColor=111827">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white&labelColor=111827">
  <img alt="React" src="https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=61DAFB&labelColor=111827">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white&labelColor=111827">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL%2016%20%2B%20pgvector-4169E1?style=flat-square&logo=postgresql&logoColor=white&labelColor=111827">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white&labelColor=111827">
</p>

</div>

<p align="center">
  <img src="docs/images/socrates-digital-avatar-cover.png" alt="Vintage illustration of Socrates as a digital AI tutor avatar" width="92%">
</p>

---

LibreTutor is a single-user learning workspace for serious self-study. Upload a PDF, EPUB, or Markdown file; LibreTutor reads the source structure, builds a chapter and lesson map, and guides each lesson through tutor dialogue, assessment, tailored exercises, grading, and a reflective tutor diary.

It is designed for people who want the patience of a private tutor, the structure of a course, and the ownership of a self-hosted tool. There is no hosted account system and no platform lock-in. You bring your own model keys, keep the data on your own server, and shape each course around the way you want to learn.

> The goal is not another chat box over a document. The goal is a book that can slowly become a course, a tutor, a practice room, and a memory of your learning.

## Contents

- [What LibreTutor Does](#what-libretutor-does)
- [Screenshots](#screenshots)
- [Learning Flow](#learning-flow)
- [Product Modules](#product-modules)
- [Application Pages](#application-pages)
- [Source Formats](#source-formats)
- [Model And Retrieval](#model-and-retrieval)
- [Self-Hosted Deployment](#self-hosted-deployment)
- [Local Development](#local-development)
- [API Surface](#api-surface)
- [Project Structure](#project-structure)
- [Security And Data](#security-and-data)
- [License](#license)

## What LibreTutor Does

LibreTutor takes a long-form source and turns it into a repeatable learning loop.

| Stage | What happens |
| --- | --- |
| Bring a source | Upload a PDF, EPUB, or Markdown document. |
| Build the map | LibreTutor extracts or infers chapters, sections, and lessons. |
| Meet the tutor | Configure the tutor's persona, tone, teaching style, and avatar per course. |
| Learn by dialogue | Each lesson opens as a focused conversation grounded in the original source. |
| Check coverage | The current dialogue is assessed against the lesson's key concepts. |
| Practice | Exercises are generated from what was covered, partially covered, or missed. |
| Receive grading | Multiple choice is checked deterministically; written answers are graded by the model. |
| Continue or retry | Passing moves the course forward; retrying starts a clean attempt for the same lesson. |
| Read the diary | The tutor writes a diary entry after each completed attempt, preserving a course-level memory. |

## Screenshots

Screenshots are stored under `screenshot/`.

| Course Library | Create Course |
| --- | --- |
| <img src="screenshot/HomePage.png" alt="Course library screenshot" width="100%"> | <img src="screenshot/create_course.png" alt="Create course screenshot" width="100%"> |
| The first page shows every course, generation status, progress, and the next place to continue. | Upload a PDF, EPUB, or Markdown source and let LibreTutor build the course map. |

| Course Generation | Lesson Map |
| --- | --- |
| <img src="screenshot/loading_course.png" alt="Course generation screenshot" width="100%"> | <img src="screenshot/course_page.png" alt="Lesson map screenshot" width="100%"> |
| Course creation shows generation status while the source is parsed and indexed. | Chapters, sections, and lessons are shown as a navigable learning path. |

| Tutor Persona | Tutor Dialogue |
| --- | --- |
| <img src="screenshot/persona.png" alt="Tutor persona configuration screenshot" width="100%"> | <img src="screenshot/dialog.png" alt="Tutor dialogue screenshot" width="100%"> |
| Configure the tutor's voice, scene, avatar, and learner context per course. | Each lesson opens into a source-grounded tutoring conversation with streaming replies. |

| Assessment | Exercises |
| --- | --- |
| <img src="screenshot/Assessment.png" alt="Assessment screenshot" width="100%"> | <img src="screenshot/excercise.png" alt="Exercises screenshot" width="100%"> |
| LibreTutor reads the dialogue and estimates concept coverage before practice. | Practice is generated from the lesson material, assessment result, and current attempt. |

| Continued Dialogue | Tutor Diary |
| --- | --- |
| <img src="screenshot/dialog2.png" alt="Continued tutor dialogue screenshot" width="100%"> | <img src="screenshot/diary.png" alt="Tutor diary screenshot" width="100%"> |
| Longer lesson conversations keep the learner inside the same attempt context. | The tutor diary becomes a chronological memory of the course. |

## Learning Flow

```mermaid
flowchart LR
    A["Course setup<br/>Upload source, build map, index chunks"]
    B["Tutor dialogue<br/>Open a lesson and learn with source-grounded guidance"]
    C["Assessment and practice<br/>Check coverage, generate exercises, grade answers"]
    D{"Progress loop<br/>Pass?"}

    A --> B --> C --> D
    D -->|Yes| E["Advance<br/>Write tutor diary"]
    D -->|No| F["Retry<br/>Write tutor diary"]
    E --> B
    F --> B
```

### 1. Course creation

The course builder accepts a source file and creates the learning skeleton:

- PDF and EPUB files use the source table of contents when available.
- Markdown files are split into virtual pages and structured from headings.
- When the source has weak or missing structure, the model helps infer a readable outline.
- Front matter and back matter can become read-only overview or closing lessons.
- The builder stores the source, creates chapters and sections, creates lesson nodes, indexes chunks, and prewarms lesson material when possible.

### 2. Lesson dialogue

Each lesson is taught as a focused conversation:

- the tutor sees the course persona and the current lesson goal;
- relevant source chunks are retrieved from PostgreSQL + pgvector;
- the prompt keeps the tutor Socratic, concrete, and anchored in the source;
- responses stream over server-sent events, so long replies do not block the page;
- every attempt keeps its own message history.

### 3. Assessment and exercises

LibreTutor does not generate practice blindly. It first asks the model to inspect the conversation and identify what the learner has covered, partially covered, or missed. That assessment then guides:

- difficulty;
- exercise count;
- question mix;
- concepts to reinforce;
- weak points to record for later review.

### 4. Grading and progress

When answers are submitted:

- multiple choice answers are checked directly;
- short answers are graded by the model with structured feedback;
- the final score decides whether the lesson is passed;
- weak concepts are saved;
- the learner can advance or retry;
- a tutor diary entry is generated for the completed attempt.

## Product Modules

| Module | Main files | What it does |
| --- | --- | --- |
| Web app shell | `frontend/src/App.tsx`, `frontend/src/components/Topbar.tsx` | Routes the learner through the course library, lesson map, tutor dialogue, exercises, diary, and settings. |
| Course library | `frontend/src/routes/HomePage.tsx`, `backend/app/courses/router.py` | Lists courses, shows generation progress, opens the next lesson, and deletes courses. |
| Course builder | `backend/app/courses/builder.py` | Parses PDF, EPUB, and Markdown sources into chapters, sections, and lessons. |
| Source retrieval | `backend/app/courses/embedding.py`, `backend/app/models/document_chunk.py` | Indexes text chunks and retrieves relevant passages with pgvector, using model embeddings when configured. |
| Tutor persona | `backend/app/courses/teacher_persona.py`, `backend/app/chat/persona_generator.py` | Stores course-specific tutor tone, scene, avatar, learner context, and generated example replies. |
| Tutor dialogue | `backend/app/chat/router.py`, `backend/app/chat/turn.py`, `backend/app/chat/socratic.py` | Builds the prompt stack, streams replies, and records messages by lesson attempt. |
| Lesson material | `backend/app/kp/materializer.py`, `backend/app/prompts/kp_material.md` | Generates lesson guidance, keyphrases, checklists, and exercise seed material. |
| Assessment | `backend/app/kp/assessor.py`, `backend/app/prompts/assessment.md` | Reads the conversation and estimates mastery before exercises are created. |
| Exercise generation | `backend/app/kp/materializer.py`, `backend/app/prompts/exercise_set.md` | Builds a tailored exercise set from source material, assessment, and target difficulty. |
| Grading | `backend/app/kp/grader.py`, `backend/app/prompts/exercise_grading.md` | Grades submissions, records feedback, and marks concepts that need more work. |
| Tutor diary | `backend/app/kp/diarist.py`, `backend/app/prompts/teacher_diary.md` | Writes a first-person tutor diary entry after each completed attempt. |
| Settings | `backend/app/settings_router.py`, `backend/app/user_llm.py`, `backend/app/crypto.py` | Stores chat and embedding configuration, encrypting API settings at rest in production. |
| Production server | `Dockerfile`, `docker-compose.yml`, `Caddyfile`, `railway.toml` | Builds the React app, serves it from FastAPI, runs migrations, and exposes the app behind Caddy or a platform router. |

## Application Pages

| Route | Purpose |
| --- | --- |
| `/` | Course library: browse courses, check generation state, continue learning. |
| `/courses/new` | Upload a source and create a new course. |
| `/courses/:courseId` | Course map with chapter, section, lesson, and progress state. |
| `/courses/:courseId/kp/:kpId` | Tutor dialogue for one lesson attempt. |
| `/courses/:courseId/kp/:kpId/assessment` | Dialogue coverage report and recommended exercise plan. |
| `/courses/:courseId/kp/:kpId/exercise` | Exercise set, answer submission, grading result, retry, and advance. |
| `/courses/:courseId/diary` | Tutor diary for the full course. |
| `/courses/:courseId/teacher-config` | Tutor persona, scene, learner context, avatar, generated examples, and rehearsal chat. |
| `/settings` | Chat model and embedding provider settings. |

## Source Formats

| Format | Support |
| --- | --- |
| PDF | Uses PyMuPDF to read pages and table-of-contents data. |
| EPUB | Uses PyMuPDF's document support to read chapter structure and text. |
| Markdown | Uses headings and virtual pages to build a source map. |

The default upload limit is 50 MB. Larger sources should be split into smaller volumes before upload.

## Model And Retrieval

LibreTutor uses a bring-your-own-key model setup.

### Chat model

The backend uses the OpenAI-compatible SDK interface. Any provider that exposes an OpenAI-compatible chat endpoint can be used by setting:

- `CHAT_BASE_URL`
- `CHAT_API_KEY`
- `CHAT_MODEL`
- `CHAT_PROVIDER`

The settings page can override environment defaults after deployment. `CHAT_PROVIDER=anthropic` is stored as provider metadata, but the runtime still expects an OpenAI-compatible endpoint or proxy.

### Embeddings

Embeddings are optional:

- with an embedding key, LibreTutor stores 1024-dimensional vectors in pgvector and performs semantic retrieval;
- without an embedding key, LibreTutor falls back to a deterministic local hash embedding, which keeps the app usable but less semantic.

The default embedding model in `.env.example` is configured for a 1024-dimensional endpoint. Changing vector dimensionality requires a matching database migration.

## Self-Hosted Deployment

The recommended production deployment is Docker Compose:

```text
Internet
   |
   v
Caddy :80/:443
   |
   v
LibreTutor app :8000
   |
   v
PostgreSQL 16 + pgvector
```

The app service serves both the API and the built React frontend. Caddy is the only public service.

### Requirements

- A Linux server with a public IP address
- A domain name pointing to the server
- Ports `80` and `443` open
- Docker Engine and Docker Compose plugin
- A chat model API key
- Optional embedding API key

LibreTutor is single-user software and has no built-in login screen. If the instance is reachable from the internet, protect it with a firewall, VPN, Caddy `basic_auth`, an OAuth proxy, mTLS, or another access-control layer.

### 1. Clone the repository

```bash
git clone https://github.com/Deriicc/LibreTutor.git
cd LibreTutor
```

### 2. Create the environment file

```bash
cp .env.example .env
```

Generate an encryption key:

```bash
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Edit `.env`:

```dotenv
DOMAIN=learn.example.com

POSTGRES_USER=app
POSTGRES_PASSWORD=replace-with-a-strong-url-safe-password
POSTGRES_DB=libretutor

ENCRYPTION_KEY=replace-with-the-generated-key
CORS_ORIGINS=["https://learn.example.com"]

CHAT_BASE_URL=https://api.deepseek.com
CHAT_API_KEY=
CHAT_MODEL=deepseek-chat
CHAT_PROVIDER=openai

EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
```

You can leave the model keys blank and fill them in from the Settings page after the app starts.

### 3. Start the stack

```bash
docker compose up -d --build
```

The app container runs:

```bash
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 4. Check health

```bash
docker compose ps
docker compose logs -f app
curl https://learn.example.com/api/health
```

Expected health response:

```json
{"status":"ok"}
```

Production API docs are intentionally hidden:

```text
https://learn.example.com/docs -> 404
https://learn.example.com/openapi.json -> 404
```

### 5. First run

1. Open `https://learn.example.com/`.
2. Go to Settings.
3. Fill in the chat model configuration.
4. Optionally fill in the embedding provider.
5. Use the test buttons to verify both providers.
6. Create your first course from a PDF, EPUB, or Markdown file.

### Maintenance

Upgrade to the latest code:

```bash
git pull
docker compose up -d --build
```

View logs:

```bash
docker compose logs -f app
docker compose logs -f caddy
docker compose logs -f db
```

Restart the app:

```bash
docker compose restart app
```

Stop the stack:

```bash
docker compose stop
```

### Backups

Back up PostgreSQL:

```bash
docker compose exec -T db pg_dump -U app libretutor > libretutor.sql
```

Back up uploaded source files:

```bash
docker compose exec -T app tar czf - -C /data uploads > uploads.tgz
```

Restore PostgreSQL into a fresh database:

```bash
cat libretutor.sql | docker compose exec -T db psql -U app libretutor
```

Restore uploads:

```bash
cat uploads.tgz | docker compose exec -T app tar xzf - -C /data
```

### Troubleshooting

| Symptom | Check |
| --- | --- |
| Caddy cannot issue a certificate | Confirm DNS points to the server and ports `80` and `443` are reachable. |
| App exits on startup | Check `ENCRYPTION_KEY`, `CORS_ORIGINS`, and `DATABASE_URL` in `docker compose logs app`. |
| Upload succeeds but generation stalls | Check app logs for model errors or rate limits. The course page will show generation status. |
| Semantic retrieval feels weak | Configure a real embedding provider on the Settings page. |
| Settings cannot be decrypted | Keep `ENCRYPTION_KEY` stable. Rotating it makes existing encrypted settings unreadable. |

### Railway

LibreTutor also includes `railway.toml` for Dockerfile-based deployment. Docker Compose remains the most complete path because it includes PostgreSQL, pgvector, upload storage, Caddy, and TLS wiring in one place.

For Railway-style deployment:

1. Create a PostgreSQL service with pgvector support.
2. Deploy this repository with the Dockerfile builder.
3. Set `PRODUCTION=true`.
4. Set `DATABASE_URL` with the `postgresql+asyncpg://` driver prefix.
5. Set `ENCRYPTION_KEY`.
6. Set `CORS_ORIGINS` to the exact public app origin.
7. Configure persistent storage for uploads if your platform filesystem is ephemeral.

## Local Development

Local development runs the backend and frontend separately.

### 1. Start PostgreSQL with pgvector

```bash
docker run --name libretutor-postgres \
  -e POSTGRES_USER=app \
  -e POSTGRES_PASSWORD=app \
  -e POSTGRES_DB=libretutor \
  -p 5432:5432 \
  -d pgvector/pgvector:pg16
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/libretutor
export CORS_ORIGINS='["http://localhost:5173"]'

alembic upgrade head
uvicorn app.main:app --reload
```

The backend listens on:

```text
http://localhost:8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend listens on:

```text
http://localhost:5173
```

### 4. Run checks

```bash
cd frontend
npm run build
```

```bash
cd backend
.venv/bin/pytest
```

## API Surface

| Area | Endpoints |
| --- | --- |
| Health | `GET /api/health` |
| Settings | `GET /api/settings`, `PUT /api/settings`, `POST /api/settings/test-chat`, `POST /api/settings/test-embedding` |
| Courses | `POST /api/courses`, `GET /api/courses`, `GET /api/courses/{course_id}`, `DELETE /api/courses/{course_id}`, `GET /api/courses/{course_id}/chapter-tree` |
| Tutor config | `GET/PUT /api/courses/{course_id}/teacher-config`, avatar upload/read/delete, few-shot regeneration, rehearsal chat |
| Diary | `GET /api/courses/{course_id}/diary` |
| Chat | `GET /api/courses/{course_id}/kp/{kp_id}/messages`, `POST /api/courses/{course_id}/kp/{kp_id}/messages`, `POST /api/courses/{course_id}/kp/{kp_id}/messages/opening` |
| Lesson | `GET /api/courses/{course_id}/kp/{kp_id}/content`, `POST /api/courses/{course_id}/kp/{kp_id}/assessment`, `POST /api/courses/{course_id}/kp/{kp_id}/exercise-set`, `POST /api/courses/{course_id}/kp/{kp_id}/advance` |
| Submissions | `POST /api/courses/{course_id}/kp/{kp_id}/submissions`, `GET /api/courses/{course_id}/kp/{kp_id}/submissions/{submission_id}`, `POST /api/courses/{course_id}/kp/{kp_id}/submissions/{submission_id}/regrade` |

Interactive API docs are available only when `PRODUCTION=false`.

## Project Structure

```text
.
├── backend/
│   ├── alembic/                 # Database migrations
│   ├── app/
│   │   ├── chat/                # Tutor dialogue and streaming turns
│   │   ├── courses/             # Uploads, course building, progress, retrieval
│   │   ├── kp/                  # Assessment, exercise generation, grading, diary
│   │   ├── models/              # SQLAlchemy models
│   │   ├── prompts/             # Prompt templates
│   │   ├── main.py              # FastAPI app
│   │   └── settings_router.py   # App-level model settings
│   └── tests/
├── frontend/
│   └── src/
│       ├── api/                 # Browser API clients
│       ├── components/          # Shared UI components
│       └── routes/              # Application pages
├── docs/
│   ├── adr/                     # Architecture decision records
│   └── images/                  # Documentation image assets
├── screenshot/                  # README screenshots
├── Dockerfile                   # Builds frontend and backend into one image
├── docker-compose.yml           # Production stack: app, db, Caddy
├── Caddyfile                    # HTTPS reverse proxy
└── railway.toml                 # Platform deployment hints
```

## Security And Data

- LibreTutor is single-user software. It expects access control to live at the network or identity-proxy layer.
- Production mode hides FastAPI docs and the OpenAPI schema.
- Production mode refuses wildcard CORS origins.
- `ENCRYPTION_KEY` is required in production so model settings can be encrypted at rest.
- Uploaded sources are stored under the configured upload directory.
- PostgreSQL stores course structure, messages, assessments, exercises, grades, diary entries, settings, and retrieval chunks.
- Protect your public origin with a network or identity layer if other people can reach it.

## License

MIT
