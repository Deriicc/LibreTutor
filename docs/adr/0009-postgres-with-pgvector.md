# 持久化：PostgreSQL + pgvector

PostgreSQL 作为统一持久化层；pgvector 扩展处理文档片段的向量搜索（用于讲解辅助和对话中的 RAG 检索）。

## Considered Options

- **SQLite + sqlite-vec**：更轻量，单文件部署，零运维。功能上完全覆盖单用户场景的 RAG 需求。
- **MongoDB**：章节树存储自然，但事务性弱、过度工程。

## Consequences

- 比 SQLite 多 0.5-1 天配置成本（本地用 Docker 跑 Postgres，云端选支持 Postgres 的平台如 Supabase / Render / Railway）。
- pgvector 在向量搜索领域成熟，未来扩展空间大。
- **向量搜索的具体使用范围尚未明确**：是 RAG 风格的对话工具？还是讲解材料的来源？还是作业素材检索？需后续决策。
- Migration 工具需要引入（Alembic 或 Prisma）。
- 应急砍功能时，可降级到 SQLite + 移除向量搜索（参见 docs/adr/ 中应急计划）。
