# 自托管部署指南（Debian 13 + Docker + Caddy）

> 面向第一次部署的人。照着一步步做即可，每一步都说明了在干什么。

## 这套东西是什么

一句话：在你自己的一台 Linux 服务器上，用 Docker 把整个产品跑起来，并自动配好 HTTPS。

启动后会有 3 个容器：

- **app**：应用本体（前端 + 后端 API 打包在一起）
- **db**：PostgreSQL 数据库（带 pgvector 向量扩展）
- **caddy**：反向代理，自动申请并续期 HTTPS 证书

访问入口都在同一个域名下：

- `https://你的域名/` → 应用
- `https://你的域名/api` → 后端接口

> 这是**单用户、无登录**版：部署好打开即用，没有注册、邀请码或管理后台。

## 开始前要准备好 3 样东西

1. **一台服务器**：Debian 13（或类似 Linux），有公网 IP，你能用 SSH 登录。
2. **一个域名**：在域名服务商（阿里云 / 腾讯云 / Cloudflare 等）把一条 **A 记录**指向服务器的公网 IP。
   - 例：域名 `learn.example.com` → A 记录填服务器 IP（如 `1.2.3.4`）。
   - 解析生效后，在本地 `ping learn.example.com` 应返回你服务器的 IP。
3. **放行端口 80 和 443**：在云厂商「安全组」和服务器防火墙里都要放行这两个端口（Caddy 申请证书和对外提供服务都要用）。

> 没有域名也能先跑起来，但 Caddy 申请不到 HTTPS 证书。强烈建议先把域名解析配好再开始。

## 第 1 步：安装 Docker

SSH 登录服务器，把下面整段粘进去执行（Docker 官方安装源）：

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

验证安装成功（两条都能打印版本号就 OK）：

```bash
docker --version
docker compose version
```

（可选）让 `docker` 命令不用每次都加 `sudo`：

```bash
sudo usermod -aG docker $USER
```

执行后**退出 SSH 重新登录**才生效。

## 第 2 步：把代码拉到服务器

```bash
git clone <你的仓库地址> self-learning-system
cd self-learning-system
```

> 把 `<你的仓库地址>` 换成你的 Git 仓库地址。之后所有命令都在 `self-learning-system` 这个目录里执行。

## 第 3 步：填写配置（最关键的一步）

复制配置模板：

```bash
cp .env.example .env
```

先生成一个加密密钥（把输出复制下来，下一步要填进 `.env`）：

```bash
python3 -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

> 这条只用 Python 自带库，会打印一串 44 位字符，就是下面要填的 `ENCRYPTION_KEY`。

然后用编辑器打开 `.env`（例如 `nano .env`），逐项填写：

| 配置项 | 填什么 | 例子 |
|--------|--------|------|
| `DOMAIN` | 你的域名（不带 `https://`） | `learn.example.com` |
| `POSTGRES_PASSWORD` | 自己起一个强密码（避开 `@ : / # ?` 这些符号） | `aB3xK9pQ2m` |
| `ENCRYPTION_KEY` | 上一步生成的那串 | `xxxx...=` |
| `CORS_ORIGINS` | 你的域名，严格按这个格式（带方括号和引号） | `["https://learn.example.com"]` |

（可选）如果你想在部署时就预置好 API key（这样打开即可用，不必再去「设置」页填），再填下面这几项；留空也没关系，启动后到「设置」页填同样可以：

```dotenv
CHAT_BASE_URL=https://api.deepseek.com
CHAT_API_KEY=你的 DeepSeek key
CHAT_MODEL=deepseek-chat
CHAT_PROVIDER=openai
EMBEDDING_API_KEY=你的 DashScope key
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
```

> ⚠️ `.env` 里有密码和 key，**绝对不要提交到 Git**。仓库已自动忽略它，你也别手动 `git add`。

## 第 4 步：启动

```bash
docker compose up -d --build
```

> 第一次会构建镜像并拉取数据库镜像，需要等几分钟。

查看启动日志：

```bash
docker compose logs -f app
```

看到 `Application startup complete` 就表示起来了（按 `Ctrl+C` 退出看日志，**不会**停掉服务）。数据库迁移会在启动时自动执行，无需手动操作。

## 第 5 步：检查是否成功

浏览器依次访问：

- `https://你的域名/` → 应用正常打开（无需登录），地址栏显示 🔒 HTTPS。
- `https://你的域名/api/health` → 显示 `{"status":"ok"}`。
- `https://你的域名/docs` → 显示 404（生产环境故意隐藏接口文档，属正常）。

全部符合就部署成功了 🎉

## 第 6 步：填入你的 API Key

打开 `https://你的域名/`，进入「设置」页，填入你的 OpenAI 兼容 Chat key 和模型（需要语义检索的话再填 Embedding key），保存即可开始建课学习。

> 如果你在第 3 步的可选项里已经填过 key，这一步可以跳过。

> ⚠️ **本版本没有登录认证**：任何能访问到这个域名的人都能使用它、消耗你配置的 API key。请确保只有你能访问——例如用云厂商安全组限制来源 IP、放在内网/VPN 后，或在 Caddy 上加一层 `basic_auth`。

## 日常维护

**更新到最新代码：**

```bash
git pull
docker compose up -d --build
```

**查看状态 / 日志：**

```bash
docker compose ps          # 看容器是否在运行
docker compose logs -f app # 实时看应用日志
```

**停止 / 启动 / 重启：**

```bash
docker compose stop        # 停止全部
docker compose up -d        # 启动
docker compose restart app # 只重启应用
```

**备份数据**（数据存在两个卷里：`pgdata` 数据库、`uploads` 用户上传文件）：

```bash
# 备份数据库（把 app / self_learning 换成你 .env 里的 POSTGRES_USER / POSTGRES_DB）
docker compose exec db pg_dump -U app self_learning > backup.sql

# 备份上传文件
docker run --rm -v self-learning-system_uploads:/data -v "$PWD":/out alpine \
  tar czf /out/uploads-backup.tgz -C /data .
```

## 常见问题

**网站打不开 / 证书申请失败？**

- 确认域名 A 记录已指向服务器 IP（`ping 你的域名` 看 IP 对不对）。
- 确认云厂商安全组 + 服务器防火墙都放行了 80 和 443。
- 看 Caddy 日志找原因：`docker compose logs caddy`。

**app 容器一直重启 / 起不来？**

- 先看日志找报错：`docker compose logs app`。
- 最常见是 `.env` 填错——比如 `CORS_ORIGINS` 格式不对（必须是 `["https://域名"]`）、或 `ENCRYPTION_KEY` 没填。

**改了 `.env` 后怎么生效？**

```bash
docker compose up -d
```

（compose 会发现配置变化并自动重建对应容器。）

**聊天报错「请先配置 API Key」？**

- 说明你既没在第 3 步的可选项里预置 key，也没在「设置」页填。两处填其一即可。

## 一些设计说明（了解即可，不影响部署）

- **数据库用的是 `pgvector/pgvector:pg16` 镜像**，不是普通 Postgres——因为产品用到向量检索，普通 Postgres 缺 `vector` 扩展会导致迁移失败。
- **app 容器的端口不对外暴露**，只有 Caddy 能访问它。请勿给 `app` 服务加 `ports:` 映射。
- **数据库迁移在启动时自动执行**（容器 `alembic upgrade head`），无需手动操作。
