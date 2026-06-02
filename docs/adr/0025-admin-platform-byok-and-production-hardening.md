---
status: superseded by 0027
---

# 管理平台、用户自带 API Key 与生产安全加固

> **已被 [0027](0027-single-user-no-auth-oss.md) 取代（开源版）。** 开源发布把产品定位为
> 单用户、无认证形态：本文涉及的双前端、cookie session、邀请码注册、管理端、CLI 管理员、
> per-user `User.api_settings`、rate limit 等大部分决策已在开源分支中移除或简化。仍然成立的
> 只有 API key 加密（迁移到单行 `AppSettings`）与生产边界中的"隐藏 docs / 拒绝 wildcard CORS /
> `ENCRYPTION_KEY` 必填"。本文保留以记录多用户托管版的历史决策。

2026-05-17 的 admin-platform 批次把系统从"单一学生端 + 全局 LLM key"推进到"学生端 + 管理端 + 用户自带 key + 可部署安全边界"。

## Context

原实现有几个部署前阻塞点：

- 所有用户共享全局 chat key，不适合真实多用户。
- 注册开放，缺少可控的发放机制。
- 管理操作没有独立后台：查看用户、课程、邀请码、删除异常课程都依赖手工 DB 操作。
- 生产模式下仍可能暴露 docs/openapi、非 Secure cookie、wildcard CORS。
- Settings 测试端点接受用户输入的 `base_url`，如果匿名开放就是 SSRF / outbound relay。
- 用户 API key 若明文落库，DB 泄漏会直接泄漏第三方 key。

## Decision

### 1. 双前端

- 学生端保留在 `frontend/`，本地端口 5173。
- 管理端新增 `frontend/admin/`，本地端口 5174。
- 两者共用后端 cookie session，通过各自 Vite `/api` proxy 访问 API。

### 2. Cookie session + 邀请码注册

- 认证使用 `session_id` HttpOnly cookie + `sessions` 表。
- 注册必须携带一次性 `InviteCode`。
- 邀请码由 admin API 生成/停用；使用时在同一事务中原子 claim。
- 无有效邀请码时，注册先拒绝，再碰 `users` 表，避免向非受邀者泄漏用户名是否存在。

### 3. CLI-only 管理员

- `is_admin` 只通过 `backend/scripts/make_admin.py` 授予/撤销。
- 管理端不提供升降级按钮，避免"网页内给自己造管理员"这类权限面。
- 管理端功能：overview、用户启停、课程查看/删除、邀请码管理、存储统计。

### 4. 用户自带 API settings

- `User.api_settings` 保存 chat/embedding 的 `api_key/base_url/model/provider`。
- 用户面向的 chat/grading/material/diary 调用解析 owning user 的 settings。
- Chat 没有全局 fallback；未配置时给用户可读错误。
- Embedding 未配置时允许降级为本地 hash embedding。

### 5. API key 加密

- `User.api_settings` 使用 `EncryptedJSONB` 包装。
- 设置了 `ENCRYPTION_KEY` 时写入 `{"_enc": "<fernet token>"}`。
- 未设置 key 的 dev 环境保留明文 pass-through。
- `PRODUCTION=true` 且无 `ENCRYPTION_KEY` 时拒绝启动。
- 旧明文行向后兼容，用户下次保存时会重写为加密 envelope。

### 6. 生产安全边界

- `PRODUCTION=true` 隐藏 `/docs`、`/redoc`、`/openapi.json`。
- Session cookie 在 production 变为 `Secure`。
- production 下禁止 `CORS_ORIGINS=["*"]`。
- 登录 10/min、注册 5/min 的 per-IP rate limit。
- Settings test-chat/test-embedding 必须登录。
- 生产部署说明写入 `README.md`。

## Consequences

- 首个管理员需要运维 bootstrap：先有一个用户，再用 `scripts/make_admin.py` 授权；注册永不自动给 admin。
- 非管理员课程数上限为 4；admin 豁免，方便管理/调试。
- 用户 API key 的生命周期归用户自己，平台不再依赖共享 chat key。
- `api_settings` 加密依赖 `ENCRYPTION_KEY` 稳定保存；丢 key 会导致已加密 settings 不可读。
- Settings 页面必须回显完整 key，方便单用户自托管场景编辑；这是产品取舍，不等于 admin 可读所有 key（admin API 不暴露 settings）。
- rate limit 当前使用 slowapi 默认内存 store，多 worker 下是 per-worker 限速；强全局限速需 Redis store。
