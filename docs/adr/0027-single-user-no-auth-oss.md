---
status: accepted
---

# 单用户、无认证的开源发布形态

开源发布把产品定位为**单用户、自托管**：使用者 clone 仓库、在「设置」页填入自己的
API key、直接开用——没有注册、登录、会话、邀请码，也没有管理后台。这条 ADR 记录由此
产生的、对 [0025](0025-admin-platform-byok-and-production-hardening.md) 的反转与简化。

## Context

[0025](0025-admin-platform-byok-and-production-hardening.md) 为多用户托管运营引入了双前端、
cookie session、邀请码注册、管理端、CLI 管理员与 per-user `User.api_settings`。开源版面向的是
"一个人在自己机器/服务器上跑自己的 AI 家教",这套多租户机制是纯粹的负担:它抬高了部署门槛
(要发邀请码、设管理员)、扩大了攻击面(认证/会话/admin),也让阅读源码的人困惑。

应用的数据模型本就**天生多用户**:`courses`/`submissions`/`weaknesses` 都挂 `user_id` 外键,
几乎每个查询都按 `Course.user_id == user.id` 过滤。单用户化要么保留外键挂一个隐藏的默认用户,
要么彻底剥离。

## Decision

### 1. 彻底剥离多用户分区（不是隐藏默认用户）

- 删除 `User` / `Session` / `InviteCode` 模型与表。
- 移除 `courses`/`submissions`/`weaknesses` 的 `user_id` 外键;`weaknesses` 唯一约束由
  `(user_id, kp_id, source)` 改为 `(kp_id, source)`。
- 重写所有按用户过滤/赋值的查询与所有权校验。换取最干净的 schema——读源码者不会再问
  "单用户为什么还有 user_id"。

### 2. 移除认证与管理端

- 删除 auth router/deps/security、cookie session、前端登录/注册页、`AuthContext`、
  `ProtectedRoute`、auth API 客户端、Topbar 的用户名/登出。
- 删除整个管理端:`frontend/admin/` 前端 + `backend/app/admin/` 路由 + `/admin` 挂载。
- 删除 per-IP rate limit(slowapi):去认证后已无被限流的路由。

### 3. API key 落到单行 `AppSettings`

- 新增 `AppSettings` 单例表(固定 `id=1`),复用既有 `EncryptedJSONB` 加密列承载
  `api_settings`。
- 「设置」页与 `settings_router` 读写这一行;`user_llm.load_api_settings(db)` 取代原先按
  `user_id` 解析。`resolve_chat` / `resolve_embedding` 签名不变(dict 入参 + env 回退)。
- 上传产物按课程归档:`upload_dir/{course_id}/`(原先按 `user_id` 归档)。

### 4. 迁移折叠为单条初始迁移

- 全新仓库、无存量库,故把原 27 条 alembic 迁移折叠为单条 `0001_initial`:先
  `CREATE EXTENSION vector`,再 `Base.metadata.create_all`,补两个无法用模型表达的性能索引
  (`ix_messages_kp_created` 与 `document_chunks` 的 HNSW 索引)。读源码者看到的就是真实 schema。

### 5. 保留的生产边界

- `PRODUCTION=true` 仍隐藏 `/docs`、`/redoc`、`/openapi.json`。
- 仍拒绝 `CORS_ORIGINS=["*"]`(防止浏览器侧任意源访问)。
- `api_settings` 仍加密落库;`PRODUCTION=true` 且无 `ENCRYPTION_KEY` 时拒绝启动。

## Consequences

- 部署即用:`docker compose up` 后打开站点直接进入,无登录跳转、无邀请码、无管理员引导。
- 这是开源版专属分叉;多用户托管版仍保留在私有分支,本仓库不含其代码。
- schema 不含任何用户概念,后续若要再支持多用户需重新引入分区(代价较大)——这是有意的取舍,
  开源版优先简洁。
- 由于无认证,API 对能访问到该端口的人完全开放;自托管者应自行用网络层(防火墙/反代鉴权/
  内网)控制可达性。CORS 不是访问控制,只约束浏览器跨源。
