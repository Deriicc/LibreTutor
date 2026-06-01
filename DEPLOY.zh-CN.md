# LibreTutor 部署指南

<p align="center">
  <strong>用 Docker Compose、PostgreSQL 和 Caddy 在自己的服务器上运行 LibreTutor。</strong>
</p>

<p align="center">
  <a href="README.zh-CN.md">中文 README</a>
  ·
  <a href="DEPLOY.md">English Deployment</a>
</p>

这是推荐的自托管生产部署方式。启动后会有三个服务：

| 服务 | 作用 |
| --- | --- |
| `caddy` | 对外 HTTPS 入口、自动证书、反向代理 |
| `app` | FastAPI API 与构建后的 React 前端 |
| `db` | 带 pgvector 的 PostgreSQL 16 |

访问入口统一在一个域名下：

```text
https://learn.example.com/           -> LibreTutor 应用
https://learn.example.com/api/health -> API 健康检查
```

## 准备条件

- 一台有公网 IP 的 Linux 服务器
- 一个解析到这台服务器的域名
- 云安全组和服务器防火墙都放行 `80` 与 `443`
- Docker Engine 和 Docker Compose 插件
- 一个 OpenAI 兼容或 Anthropic 兼容的 Chat API Key
- 可选的 Embedding API Key，用于更好的语义检索

LibreTutor 没有内置登录系统。如果域名能被公网访问，请用防火墙、VPN、Caddy `basic_auth`、OAuth proxy 或 mTLS 做访问控制。

## 1. 安装 Docker

Debian 或 Ubuntu 可执行：

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

验证：

```bash
docker --version
docker compose version
```

可选：让当前用户免 `sudo` 使用 Docker：

```bash
sudo usermod -aG docker $USER
```

执行后退出 SSH 并重新登录。

## 2. 拉取 LibreTutor

```bash
git clone git@github.com:Deriicc/LibreTutor.git
cd LibreTutor
```

如果你部署自己的 fork，把仓库地址换成你的地址。

## 3. 配置环境变量

```bash
cp .env.example .env
```

生成加密密钥：

```bash
python3 -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

编辑 `.env`：

```dotenv
DOMAIN=learn.example.com
POSTGRES_USER=app
POSTGRES_PASSWORD=replace-with-a-strong-url-safe-password
POSTGRES_DB=self_learning
ENCRYPTION_KEY=replace-with-the-generated-key
CORS_ORIGINS=["https://learn.example.com"]
```

可选模型默认值：

```dotenv
CHAT_BASE_URL=https://api.deepseek.com
CHAT_API_KEY=
CHAT_MODEL=deepseek-chat
CHAT_PROVIDER=openai

EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
```

模型 Key 可以留空，启动后在 LibreTutor 的设置页填写。

## 4. 启动服务

```bash
docker compose up -d --build
```

查看应用日志：

```bash
docker compose logs -f app
```

`app` 容器会在启动前自动执行数据库迁移。

## 5. 检查部署

打开：

```text
https://learn.example.com/
```

检查健康接口：

```bash
curl https://learn.example.com/api/health
```

期望返回：

```json
{"status":"ok"}
```

生产模式会隐藏 API 文档：

```text
https://learn.example.com/docs -> 404
```

## 6. 配置模型 Key

打开应用，进入设置页，填写：

- Chat 服务类型
- Base URL
- API Key
- 模型名称
- 可选的 Embedding 服务配置

设置了 `ENCRYPTION_KEY` 后，这些配置会加密存储在 PostgreSQL 中。

## 访问控制

LibreTutor 是私人单用户工作台。不要在没有访问边界的情况下公开发布。

推荐方式：

| 方式 | 适用场景 |
| --- | --- |
| 云防火墙 / 安全组 | 只允许固定 IP 访问 |
| VPN 或私有网络 | 家庭服务器或私有团队 |
| Caddy `basic_auth` | 简单密码保护 |
| OAuth proxy | 多人共享入口 |
| mTLS | 严格私有基础设施 |

`app` 服务不会暴露到宿主机端口，只有 Compose 网络里的 Caddy 能访问它。

## 日常维护

更新：

```bash
git pull
docker compose up -d --build
```

查看状态和日志：

```bash
docker compose ps
docker compose logs -f app
docker compose logs -f caddy
```

重启：

```bash
docker compose restart app
```

停止：

```bash
docker compose stop
```

## 备份

备份 PostgreSQL：

```bash
docker compose exec -T db pg_dump -U app self_learning > libretutor.sql
```

备份上传资料：

```bash
docker compose exec -T app tar czf - -C /data uploads > uploads.tgz
```

恢复到空数据库：

```bash
cat libretutor.sql | docker compose exec -T db psql -U app self_learning
```

## 常见问题

### Caddy 申请不到证书

- 确认域名 A 或 AAAA 记录指向服务器。
- 确认 `80` 和 `443` 已放行。
- 查看 Caddy 日志：

```bash
docker compose logs caddy
```

### app 容器反复重启

查看日志：

```bash
docker compose logs app
```

常见原因：

- `CORS_ORIGINS` 不是合法 JSON
- 没有设置 `ENCRYPTION_KEY`
- 数据库配置不正确
- 数据库健康检查未通过

### 聊天提示缺少模型设置

在应用设置页填写 Chat 配置，或在 `.env` 中预填 `CHAT_API_KEY`、`CHAT_BASE_URL`、`CHAT_MODEL` 和 `CHAT_PROVIDER`。

### 上传失败

默认上传上限是 50 MB。支持格式：

```text
.pdf
.epub
.md
.markdown
```

## 平台部署

仓库包含 `railway.toml`，可用于基于 Dockerfile 的 Railway 部署。若平台已经提供 HTTPS 与反向代理，就不需要 Caddy。仍需准备带 pgvector 的 PostgreSQL，并设置 `PRODUCTION=true`、`ENCRYPTION_KEY` 和精确的 `CORS_ORIGINS`。
