# LibreTutor

<p align="center">
  <strong>把书稿和笔记变成一条可对话、可练习、可回看的自学路径。</strong>
</p>

<p align="center">
  <a href="README.md">English</a>
  ·
  <a href="DEPLOY.zh-CN.md">部署指南</a>
  ·
  <a href="DEPLOY.md">English Deployment</a>
</p>

<p align="center">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-111827?style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="React" src="https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=111827">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL%20%2B%20pgvector-4169E1?style=flat-square&logo=postgresql&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white">
</p>

LibreTutor 是一个单用户、自托管、使用你自己的模型 Key 的 AI 自学工作台。上传 PDF、EPUB 或 Markdown，LibreTutor 会读取资料结构，生成学习路径，并用一位可配置的 AI 导师陪你完成对话、评估、练习、批阅和导师手记。

它面向私人学习、独立阅读和严肃自学。没有托管账号层，也不绑定任何平台。

## 为什么是 LibreTutor

很多文档聊天工具只停留在“问文件”。LibreTutor 关注的是完整学习循环：

| 环节 | LibreTutor 做什么 |
| --- | --- |
| 上传 | 放入 PDF、EPUB 或 Markdown 资料。 |
| 结构化 | 抽取或推断章节、节与学习段。 |
| 对话 | 由可配置的 AI 导师进行聚焦讲解。 |
| 评估 | 根据刚才的对话判断本段掌握情况。 |
| 练习 | 按已覆盖和未掌握的内容生成题卷。 |
| 回顾 | 导师为本次学习写下一篇手记。 |

## 特性

- **默认私有**：部署在自己的服务器上，使用自己的模型 Key。
- **保留书本结构**：不把一本书打散成无上下文的文本块。
- **可塑造的导师**：为每门课设置导师的人设、语气、关系和讲法。
- **流式对话**：用 SSE 传输长回复，交互更顺滑。
- **基于原文检索**：用 pgvector 把相关原文片段带入学习对话。
- **先评估再出题**：题卷会参考这次对话中已掌握和未覆盖的内容。
- **重试互不污染**：每次重试都有独立的对话、题卷、批阅和手记。
- **一体化镜像**：生产镜像同时服务 React 前端和 FastAPI 后端。

## 快速开始

公网或半私有服务器建议使用 Docker Compose：

```bash
git clone git@github.com:Deriicc/LibreTutor.git
cd LibreTutor
cp .env.example .env
```

编辑 `.env`：

```dotenv
DOMAIN=learn.example.com
POSTGRES_PASSWORD=replace-with-a-strong-password
ENCRYPTION_KEY=replace-with-a-generated-key
CORS_ORIGINS=["https://learn.example.com"]
```

生成加密密钥：

```bash
python3 -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

启动：

```bash
docker compose up -d --build
```

打开：

```text
https://learn.example.com/
```

完整步骤见 [DEPLOY.zh-CN.md](DEPLOY.zh-CN.md)。

## 本地开发

LibreTutor 需要 PostgreSQL 16 + pgvector、Python 3.11+ 和 Node 20+。

```bash
sudo apt-get update
sudo apt-get install -y postgresql-16 postgresql-16-pgvector
sudo service postgresql start

sudo -u postgres psql -c "CREATE USER app WITH PASSWORD 'app';"
sudo -u postgres psql -c "CREATE DATABASE self_learning OWNER app;"
sudo -u postgres psql -d self_learning -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

创建 `backend/.env`：

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

安装依赖并迁移数据库：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head

cd ../frontend
npm install
```

启动本地应用：

```bash
./start.sh
```

本地端点：

```text
应用：  http://localhost:5173
API：   http://localhost:8000
健康：  http://localhost:8000/api/health
```

## 模型配置

LibreTutor 默认使用 OpenAI 兼容的 Chat 配置，也可以在设置页选择 Anthropic 兼容服务。

Embedding 是可选项。未配置时，LibreTutor 会退回到本地确定性哈希向量，保证应用仍可运行；配置真实 embedding 模型后，语义检索质量会更好。

## 架构

```text
资料文件
  -> 学习路径
  -> 学习段
  -> 导师对话
  -> 掌握评估
  -> 练习题卷
  -> 批阅
  -> 导师手记
```

| 层 | 技术 |
| --- | --- |
| 前端 | React 18, TypeScript, Vite |
| 后端 | FastAPI, async SQLAlchemy, Alembic |
| 数据库 | PostgreSQL 16, pgvector |
| 解析 | PyMuPDF 解析 PDF 与 EPUB，Markdown 虚拟分页 |
| 模型 | 用户自行配置 Chat 与 Embedding 服务 |
| 生产部署 | Docker Compose, Caddy, 单应用镜像 |

代码结构：

```text
backend/app/
  chat/        导师对话与 prompt 组装
  courses/     上传、学习路径构建、检索、报告输入
  kp/          学习物料、评估、题卷、批阅、手记
  models/      SQLAlchemy 模型
  prompts/     导师、评估、出题、手记 prompt

frontend/src/
  routes/      页面
  components/  共享组件
  api/         浏览器端 API client
```

## 安全模型

LibreTutor 是单用户应用，没有内置登录页。任何能访问应用的人，都能使用已配置的模型 Key，也能看到库里的课程。

如果暴露到公网，请至少放在以下一种边界之后：

- 只允许固定 IP 访问的防火墙或云安全组
- VPN 或私有网络
- Caddy `basic_auth`
- OAuth proxy
- mTLS

生产模式要求设置 `ENCRYPTION_KEY`，并会加密数据库中的模型设置。

## 常用命令

```bash
# 本地开发
./start.sh
./start.sh stop
./start.sh logs
./start.sh status

# 生产部署
docker compose up -d --build
docker compose logs -f app
docker compose ps

# 后端测试
cd backend
source .venv/bin/activate
pytest
```

## 文档

- [中文部署指南](DEPLOY.zh-CN.md)
- [English deployment guide](DEPLOY.md)
- [架构决策记录](docs/adr)
- [项目上下文](CONTEXT.md)

## 许可证

MIT License. 见 [LICENSE](LICENSE)。
