# KnowledgePoint 内容懒加载：进入时临时提炼讲解材料

## Status

**Superseded by ADR-0020**（2026-05-14）。现在的实施是课程构建后**异步 prewarm** 所有 KP 的 `KPMaterial`，并发受 `kp_extraction_concurrency` 限制；本 ADR 担心的"几十分钟延迟"通过 prewarm 不阻塞 chapter tree commit + 后台并发解决。Lazy fallback 路径保留（`kp.router.get_kp_content` 在 material 缺失时同步生成）。

下方原文保留以记录历史决策。

---

章节树生成时只确定每个 **KnowledgePoint** 在源资料中的边界（页码或字段范围），不预生成讲解材料。当用户首次进入某个 KP 时，系统才即时读取该段内容、由 LLM 提炼讲解切入点（写入苏格拉底对话的 system prompt）。

## Considered Options

- **章节树生成时一次性预生成所有 KP 讲解材料**：80 个 KP 各调一次 LLM = Course 创建延迟爆炸（数十分钟），用户体验灾难。
- **三层切分：章节树之下，KP 内部还有"知识片段"子单元**：增加一层颗粒度，术语和数据模型膨胀，且与已固定的 4 层结构冲突。

## Consequences

- KP 进入延迟从零变为 1-3 秒（LLM 提炼），但首次之后可以缓存到 DB；缓存策略在工程实现时决定。
- 提炼出的"讲解材料"的具体形态（要点列表？提问大纲？关键概念？）在苏格拉底 prompt 设计时一并决定。
- 章节树生成的 LLM 输出 schema 中，每个 KP 节点必须保留"在原资料中的位置"字段（页码范围、字符偏移或类似），否则懒加载时无法定位原文。
