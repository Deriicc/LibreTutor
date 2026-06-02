<div align="center">

<h1>LibreTutor</h1>

<p>
  <strong><i>把书稿、笔记和长文档变成一条<br>可对话、可练习、可回看的自学路径。</i></strong>
</p>

<p>
  <a href="#libretutor-能做什么">功能</a>
  &nbsp;·&nbsp;
  <a href="#界面预览">界面预览</a>
  &nbsp;·&nbsp;
  <a href="#自托管部署">部署</a>
  &nbsp;·&nbsp;
  <a href="README.md">English</a>
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
  <img src="docs/images/socrates-digital-avatar-cover.png" alt="苏格拉底数字 AI 导师分身复古插画" width="92%">
</p>

---

LibreTutor 是一个面向严肃自学的单用户学习工作台。上传 PDF、EPUB 或 Markdown 后，它会读取资料结构，生成章、节与课的学习地图，并围绕每一课完成导师对话、掌握度评估、针对性练习、批阅反馈和导师手记。

它适合希望长期阅读、系统学习、保留学习痕迹的人：既有课程的秩序，也有私人导师的陪伴；既能使用大模型的解释能力，也把资料、进度和 API Key 留在自己的服务器上。

> LibreTutor 不是“对着文档聊天”的外壳。它想做的是：让一本书慢慢变成课程、导师、练习室和一段可以回看的学习记忆。

## 目录

- [LibreTutor 能做什么](#libretutor-能做什么)
- [界面预览](#界面预览)
- [完整学习流程](#完整学习流程)
- [核心模块](#核心模块)
- [页面说明](#页面说明)
- [资料格式](#资料格式)
- [模型与检索](#模型与检索)
- [自托管部署](#自托管部署)
- [本地开发](#本地开发)
- [API 概览](#api-概览)
- [项目结构](#项目结构)
- [安全与数据](#安全与数据)
- [许可证](#许可证)

## LibreTutor 能做什么

LibreTutor 将长资料整理为一个可重复的学习循环。

| 环节 | 说明 |
| --- | --- |
| 放入资料 | 上传 PDF、EPUB 或 Markdown。 |
| 生成地图 | 抽取或推断章、节与课，形成可导航的学习路径。 |
| 设定导师 | 为每门课配置导师人设、语气、教学方式、学习者背景和头像。 |
| 对话学习 | 每一课都以一次聚焦的导师对话展开，并尽量回到原文。 |
| 覆盖评估 | 根据当前对话判断哪些概念已经覆盖、部分覆盖或遗漏。 |
| 生成练习 | 按评估结果生成适合当前状态的练习题。 |
| 批阅反馈 | 选择题直接校验，简答题由模型给出结构化批阅。 |
| 前进或重试 | 通过后进入下一课；未通过可开启同一课的新尝试。 |
| 导师手记 | 每次完成尝试后，导师写下一篇课程内的学习手记。 |

## 界面预览

截图存放在 `screenshot/` 目录。

| 课程书架 | 创建课程 |
| --- | --- |
| <img src="screenshot/HomePage.png" alt="课程书架截图" width="100%"> | <img src="screenshot/create_course.png" alt="创建课程截图" width="100%"> |
| 查看全部课程、生成状态、学习进度和下一次继续的位置。 | 上传 PDF、EPUB 或 Markdown，让 LibreTutor 生成课程地图。 |

| 课程生成 | 课程地图 |
| --- | --- |
| <img src="screenshot/loading_course.png" alt="课程生成截图" width="100%"> | <img src="screenshot/course_page.png" alt="课程地图截图" width="100%"> |
| 创建课程时展示资料解析、索引和生成状态。 | 章、节、课构成一条可展开、可继续的学习路径。 |

| 导师人设 | 导师对话 |
| --- | --- |
| <img src="screenshot/persona.png" alt="导师人设截图" width="100%"> | <img src="screenshot/dialog.png" alt="导师对话截图" width="100%"> |
| 为每门课配置导师语气、场景、头像和学习者背景。 | 每一课进入一段基于原文的流式导师对话。 |

| 掌握度评估 | 针对性练习 |
| --- | --- |
| <img src="screenshot/Assessment.png" alt="掌握度评估截图" width="100%"> | <img src="screenshot/excercise.png" alt="练习截图" width="100%"> |
| 先阅读本次对话，再判断概念覆盖度和练习难度。 | 按原文、对话和评估结果生成当前最该练的题目。 |

| 连续对话 | 导师手记 |
| --- | --- |
| <img src="screenshot/dialog2.png" alt="连续导师对话截图" width="100%"> | <img src="screenshot/diary.png" alt="导师手记截图" width="100%"> |
| 较长的学习对话会保留在同一次尝试上下文中。 | 每次完成尝试后，导师为课程留下连续的学习记忆。 |

## 完整学习流程

```mermaid
flowchart LR
    A[上传资料] --> B[解析目录和页面]
    B --> C[生成课程树]
    C --> D[索引原文片段]
    D --> E[打开一课]
    E --> F[与导师对话]
    F --> G[评估覆盖度]
    G --> H[生成练习]
    H --> I[提交答案]
    I --> J[批阅并记录薄弱点]
    J --> K{是否通过}
    K -->|通过| L[进入下一课]
    K -->|未通过| M[重试本课]
    L --> N[生成导师手记]
    M --> N
    N --> E
```

### 1. 创建课程

课程构建器会接收资料文件并生成学习骨架：

- PDF 和 EPUB 会优先读取自带目录。
- Markdown 会根据标题与虚拟页建立结构。
- 当资料目录很弱或缺失时，模型会辅助推断可读的课程大纲。
- 前言、导言、结语、附录等内容可以成为只读的概览课或收束课。
- 构建过程会写入课程、章、节、课节点，索引原文片段，并尽可能预热每课材料。

### 2. 导师对话

每一课都围绕当前主题展开：

- 导师会看到本课程的人设、场景、语气和学习者背景。
- 系统会从 PostgreSQL + pgvector 中取回相关原文片段。
- 对话提示词要求导师保持苏格拉底式、具体、克制，并尽量基于资料。
- 长回复通过 SSE 流式返回，页面不需要等待整段生成完成。
- 每一次重试都有独立的消息历史，互不污染。

### 3. 评估与练习

LibreTutor 不会一开始就盲目出题。它会先让模型阅读本课对话，判断：

- 哪些概念已经被充分覆盖；
- 哪些概念只被部分覆盖；
- 哪些关键点还没有触及；
- 当前更适合什么难度；
- 应该出多少题、侧重哪些题型。

练习生成会参考这份评估，以及本课的材料、关键词、检查清单和原文片段。

### 4. 批阅与推进

提交答案后：

- 选择题会由程序直接判定；
- 简答题会由模型给出批阅和反馈；
- 总分决定本课是否通过；
- 低分概念会被记录为薄弱点；
- 学习者可以进入下一课，也可以开启一次新的重试；
- 尝试结束后，导师手记会被异步生成并写入课程记忆。

## 核心模块

| 模块 | 主要文件 | 作用 |
| --- | --- | --- |
| 前端外壳 | `frontend/src/App.tsx`, `frontend/src/components/Topbar.tsx` | 组织课程书架、课程地图、导师对话、练习、手记和设置页。 |
| 课程书架 | `frontend/src/routes/HomePage.tsx`, `backend/app/courses/router.py` | 展示课程、生成状态、进度、继续学习入口和删除操作。 |
| 课程构建 | `backend/app/courses/builder.py` | 将 PDF、EPUB、Markdown 解析为章、节与课。 |
| 原文检索 | `backend/app/courses/embedding.py`, `backend/app/models/document_chunk.py` | 将文本切块并写入 pgvector，供对话和练习检索。 |
| 导师人设 | `backend/app/courses/teacher_persona.py`, `backend/app/chat/persona_generator.py` | 保存每门课的导师语气、场景、头像、学习者背景和示例回复。 |
| 导师对话 | `backend/app/chat/router.py`, `backend/app/chat/turn.py`, `backend/app/chat/socratic.py` | 组织提示词、流式回复和按课次保存的消息历史。 |
| 课内材料 | `backend/app/kp/materializer.py`, `backend/app/prompts/kp_material.md` | 生成课内讲解材料、关键词、检查清单和练习种子。 |
| 掌握评估 | `backend/app/kp/assessor.py`, `backend/app/prompts/assessment.md` | 根据对话判断本课掌握度，并建议练习难度和数量。 |
| 练习生成 | `backend/app/kp/materializer.py`, `backend/app/prompts/exercise_set.md` | 结合原文、评估和目标难度生成题卷。 |
| 批阅反馈 | `backend/app/kp/grader.py`, `backend/app/prompts/exercise_grading.md` | 批阅答案、生成反馈、记录薄弱概念。 |
| 导师手记 | `backend/app/kp/diarist.py`, `backend/app/prompts/teacher_diary.md` | 在每次尝试结束后写入第一人称导师手记。 |
| 模型设置 | `backend/app/settings_router.py`, `backend/app/user_llm.py`, `backend/app/crypto.py` | 保存 Chat 与 Embedding 配置，生产环境加密存储 API 设置。 |
| 生产服务 | `Dockerfile`, `docker-compose.yml`, `Caddyfile`, `railway.toml` | 构建前端、运行后端、执行迁移、连接数据库并暴露 HTTPS 入口。 |

## 页面说明

| 路由 | 页面 |
| --- | --- |
| `/` | 课程书架：浏览课程、查看生成状态、继续学习。 |
| `/courses/new` | 创建课程：上传资料并开始生成。 |
| `/courses/:courseId` | 课程地图：查看章、节、课与学习进度。 |
| `/courses/:courseId/kp/:kpId` | 导师对话：进入某一课的学习尝试。 |
| `/courses/:courseId/kp/:kpId/assessment` | 掌握度评估：查看对话覆盖情况和练习建议。 |
| `/courses/:courseId/kp/:kpId/exercise` | 练习页：答题、提交、等待批阅、重试或前进。 |
| `/courses/:courseId/diary` | 导师手记：浏览整门课的学习记录。 |
| `/courses/:courseId/teacher-config` | 导师设定：配置人设、场景、学习者背景、头像和试聊。 |
| `/settings` | 模型设置：配置 Chat 与 Embedding 服务。 |

## 资料格式

| 格式 | 支持方式 |
| --- | --- |
| PDF | 通过 PyMuPDF 读取页面文本和目录。 |
| EPUB | 通过 PyMuPDF 读取电子书结构和文本。 |
| Markdown | 根据标题结构与虚拟页生成课程地图。 |

默认上传大小上限是 50 MB。很大的资料建议先拆成更适合学习的分册。

## 模型与检索

LibreTutor 使用自带 Key 的模型配置方式。

### Chat 模型

后端使用 OpenAI-compatible SDK 接口。只要服务商提供 OpenAI 兼容的 Chat endpoint，就可以通过以下配置接入：

- `CHAT_BASE_URL`
- `CHAT_API_KEY`
- `CHAT_MODEL`
- `CHAT_PROVIDER`

部署后也可以在网页设置页修改这些配置。`CHAT_PROVIDER=anthropic` 会作为服务商元数据保存，但运行时仍需要 OpenAI 兼容 endpoint 或兼容代理。

### Embedding 模型

Embedding 是可选项：

- 配置 Embedding Key 后，LibreTutor 会把 1024 维向量写入 pgvector，并用于语义检索。
- 不配置 Embedding Key 时，系统会退回到本地确定性 hash embedding，功能仍可使用，但语义能力较弱。

`.env.example` 默认按 1024 维 embedding endpoint 配置。若要更换向量维度，需要同步调整数据库迁移。

## 自托管部署

推荐的生产部署方式是 Docker Compose：

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

`app` 服务同时提供 API 和构建后的 React 前端。只有 Caddy 对公网开放。

### 准备条件

- 一台有公网 IP 的 Linux 服务器
- 一个解析到服务器的域名
- 已放行 `80` 和 `443` 端口
- Docker Engine 与 Docker Compose 插件
- 一个 Chat 模型 API Key
- 可选的 Embedding API Key

LibreTutor 是单用户软件，没有内置登录页。如果实例能被公网访问，请使用防火墙、VPN、Caddy `basic_auth`、OAuth proxy、mTLS 或其他访问控制层保护入口。

### 1. 拉取仓库

```bash
git clone https://github.com/Deriicc/LibreTutor.git
cd LibreTutor
```

### 2. 创建环境变量

```bash
cp .env.example .env
```

生成加密密钥：

```bash
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

编辑 `.env`：

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

模型 Key 可以先留空，启动后在网页设置页填写。

### 3. 启动服务

```bash
docker compose up -d --build
```

应用容器启动时会执行：

```bash
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 4. 检查健康状态

```bash
docker compose ps
docker compose logs -f app
curl https://learn.example.com/api/health
```

期望返回：

```json
{"status":"ok"}
```

生产模式会隐藏 API 文档：

```text
https://learn.example.com/docs -> 404
https://learn.example.com/openapi.json -> 404
```

### 5. 第一次使用

1. 打开 `https://learn.example.com/`。
2. 进入 Settings。
3. 填写 Chat 模型配置。
4. 可选填写 Embedding 配置。
5. 使用测试按钮确认模型可用。
6. 上传 PDF、EPUB 或 Markdown，创建第一门课。

### 日常维护

更新代码并重建：

```bash
git pull
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f app
docker compose logs -f caddy
docker compose logs -f db
```

重启应用：

```bash
docker compose restart app
```

停止服务：

```bash
docker compose stop
```

### 备份与恢复

备份 PostgreSQL：

```bash
docker compose exec -T db pg_dump -U app libretutor > libretutor.sql
```

备份上传资料：

```bash
docker compose exec -T app tar czf - -C /data uploads > uploads.tgz
```

恢复 PostgreSQL：

```bash
cat libretutor.sql | docker compose exec -T db psql -U app libretutor
```

恢复上传资料：

```bash
cat uploads.tgz | docker compose exec -T app tar xzf - -C /data
```

### 常见问题

| 现象 | 检查项 |
| --- | --- |
| Caddy 无法签发证书 | 确认 DNS 指向服务器，并且 `80`、`443` 端口可访问。 |
| 应用启动后退出 | 查看 `docker compose logs app`，检查 `ENCRYPTION_KEY`、`CORS_ORIGINS`、`DATABASE_URL`。 |
| 上传成功但课程生成卡住 | 查看应用日志中的模型错误或限流信息，课程页会显示生成状态。 |
| 检索效果较弱 | 在设置页配置真实 Embedding 服务。 |
| 设置页配置无法解密 | `ENCRYPTION_KEY` 需要保持稳定，轮换后旧配置会无法读取。 |

### Railway

项目包含 `railway.toml`，可用于 Dockerfile 构建式部署。更推荐 Docker Compose，因为它已经把 PostgreSQL、pgvector、上传存储、Caddy 和 TLS 串在一起。

如果使用 Railway 或类似平台：

1. 创建支持 pgvector 的 PostgreSQL 服务。
2. 使用 Dockerfile 部署本仓库。
3. 设置 `PRODUCTION=true`。
4. 设置带 `postgresql+asyncpg://` 驱动前缀的 `DATABASE_URL`。
5. 设置 `ENCRYPTION_KEY`。
6. 将 `CORS_ORIGINS` 设置为精确的公网访问域名。
7. 如果平台文件系统是临时的，需要单独配置上传文件的持久化存储。

## 本地开发

本地开发时，后端和前端分开运行。

### 1. 启动 PostgreSQL + pgvector

```bash
docker run --name libretutor-postgres \
  -e POSTGRES_USER=app \
  -e POSTGRES_PASSWORD=app \
  -e POSTGRES_DB=libretutor \
  -p 5432:5432 \
  -d pgvector/pgvector:pg16
```

### 2. 后端

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

后端地址：

```text
http://localhost:8000
```

### 3. 前端

```bash
cd frontend
npm install
npm run dev
```

前端地址：

```text
http://localhost:5173
```

### 4. 检查命令

```bash
cd frontend
npm run build
```

```bash
cd backend
.venv/bin/pytest
```

## API 概览

| 范围 | 接口 |
| --- | --- |
| 健康检查 | `GET /api/health` |
| 设置 | `GET /api/settings`, `PUT /api/settings`, `POST /api/settings/test-chat`, `POST /api/settings/test-embedding` |
| 课程 | `POST /api/courses`, `GET /api/courses`, `GET /api/courses/{course_id}`, `DELETE /api/courses/{course_id}`, `GET /api/courses/{course_id}/chapter-tree` |
| 导师配置 | `GET/PUT /api/courses/{course_id}/teacher-config`，头像上传/读取/删除，示例回复再生成，试聊 |
| 导师手记 | `GET /api/courses/{course_id}/diary` |
| 对话 | `GET /api/courses/{course_id}/kp/{kp_id}/messages`, `POST /api/courses/{course_id}/kp/{kp_id}/messages`, `POST /api/courses/{course_id}/kp/{kp_id}/messages/opening` |
| 课 | `GET /api/courses/{course_id}/kp/{kp_id}/content`, `POST /api/courses/{course_id}/kp/{kp_id}/assessment`, `POST /api/courses/{course_id}/kp/{kp_id}/exercise-set`, `POST /api/courses/{course_id}/kp/{kp_id}/advance` |
| 提交 | `POST /api/courses/{course_id}/kp/{kp_id}/submissions`, `GET /api/courses/{course_id}/kp/{kp_id}/submissions/{submission_id}`, `POST /api/courses/{course_id}/kp/{kp_id}/submissions/{submission_id}/regrade` |

交互式 API 文档只在 `PRODUCTION=false` 时开放。

## 项目结构

```text
.
├── backend/
│   ├── alembic/                 # 数据库迁移
│   ├── app/
│   │   ├── chat/                # 导师对话和流式回复
│   │   ├── courses/             # 上传、课程构建、进度、检索
│   │   ├── kp/                  # 评估、练习生成、批阅、手记
│   │   ├── models/              # SQLAlchemy 模型
│   │   ├── prompts/             # 提示词模板
│   │   ├── main.py              # FastAPI 应用
│   │   └── settings_router.py   # 应用级模型设置
│   └── tests/
├── frontend/
│   └── src/
│       ├── api/                 # 浏览器端 API client
│       ├── components/          # 共享组件
│       └── routes/              # 应用页面
├── docs/
│   ├── adr/                     # 架构决策记录
│   └── images/                  # 文档图片资源
├── screenshot/                  # README 截图
├── Dockerfile                   # 将前端和后端构建为一个镜像
├── docker-compose.yml           # 生产服务：app、db、Caddy
├── Caddyfile                    # HTTPS 反向代理
└── railway.toml                 # 平台部署提示
```

## 安全与数据

- LibreTutor 是单用户软件，访问控制应放在网络层或身份代理层。
- 生产模式会隐藏 FastAPI docs 和 OpenAPI schema。
- 生产模式会拒绝 wildcard CORS。
- 生产模式必须设置 `ENCRYPTION_KEY`，用于加密模型 API 设置。
- 上传资料存储在配置的 upload 目录中。
- PostgreSQL 存储课程结构、消息、评估、练习、批阅、导师手记、模型设置和检索片段。
- 如果公网可以访问你的实例，请务必用网络层或身份层保护入口。

## 许可证

MIT
