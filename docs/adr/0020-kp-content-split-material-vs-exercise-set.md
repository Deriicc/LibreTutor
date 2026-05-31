# KP 内容拆分：KPMaterial（稳定）vs KPExerciseSet（裁剪）

## Status

Accepted, 2026-05-14.

Supersedes:
- ADR-0002（KP 内容懒加载——material 现在课程构建后预生成，不再懒加载）
- ADR-0013（作业题与 KP 讲解材料一起懒加载——两者现在拆成两次独立 LLM 调用）

Compatible with / refines:
- ADR-0019（对话驱动的作业生成）—— 实施层面把对话→作业的桥从单一 `generate_kp_content` 调用拆开
- ADR-0014（Pro-QuEST 命题原则）—— 现在只 apply 到 exercise_set prompt
- ADR-0016（三层 prompt 架构）—— Layer 3 现在读 `KPMaterial` 而非合并资源

## Context

ADR-0002 + ADR-0013 把"讲解材料 + 作业题"放进**一次 LLM 调用**，写入单张 `KnowledgePointContent` 表。ADR-0019 之后又给这次调用加了 `covered_concepts` / `difficulty` / `count` 参数，试图让作业 dialogue-tailored。

实际跑下来三个具体问题：

1. **默认 UX 路径下，dialogue tailoring 失效。** `KnowledgePointContent` 主键是 `(kp_id, attempt)`，`get_kp_content` 看到 cache hit 就直接返回。如果学生没主动改难度/题量去 bump attempt，他做的就是 prewarm 时生成的 baseline——里面 `covered_concepts=None`，没有任何对话裁剪。**这是个静默 bug**，不是设计选择。

2. **改 exercises 浪费 70% tokens。** "想 fix 题目"必须重跑完整 prompt——layer3_prompt + keyphrases + knowledge_checklist 也跟着重新生成，但它们派生自 PDF，本来不应该重生成。

3. **概念混淆带来命名/职责歧义。** 同一张表 `KnowledgePointContent` 既是"chat Layer 3 需要的资源"又是"作业页需要的资源"，两个消费者的生命周期完全不同（一个跟 KP 走，一个跟 attempt 走），合一张表无法表达。

## Decision

**拆成两个领域概念，两张表，两次独立的 LLM 调用，两次独立的触发：**

### KPMaterial（PDF 派生的稳定物料）

- 字段：`layer3_prompt`, `keyphrases`, `knowledge_checklist`, `layer2_snapshot`
- 主键：`kp_id`（一对一）
- 生成：课程构建完成后**异步** prewarm（`kp.prewarm.prewarm_kp_materials`），一次 LLM 调用 / KP，prompt 在 `prompts/kp_material.md`
- 消费者：苏格拉底对话的 Layer 3、KPAssessment 的 checklist 输入

### KPExerciseSet（dialogue-tailored 的题集）

- 字段：`exercises`
- 主键：`(kp_id, attempt)`（多对一，retry 时新建）
- 生成：`POST /assessment` 写完 `KPAssessment` 后**异步** tailor（`kp.materializer.tailor_exercise_set`），一次 LLM 调用 / attempt，prompt 在 `prompts/exercise_set.md`，输入：
  - `KPMaterial.keyphrases`（作命题锚点）
  - `KPAssessment.covered + partial`（硬约束 covered_concepts）
  - 概率抽取的薄弱点（review 注入，参见 ADR-0005、ADR-0015）
  - `KPAssessment.suggested_difficulty + suggested_count`
- 消费者：作业页、grader、学习报告

### 触发时序

```
课程构建 ─→ index_course_chunks（RAG）
         ─→ prewarm_kp_materials（每 KP 一次 LLM 调用）
                │
                ▼ 学生开始对话（Layer 3 已就绪）
                ▼ 学生结束对话，POST /assessment
                ▼ run_assessment（读 material.checklist + history）
                ▼ asyncio.create_task(tailor_exercise_set)
                ▼ 学生点 /content
                ▼ cache hit → 返回 tailored exercises
```

### Lazy 兜底

如果学生跳过评估直接点作业，`/content` 同步触发 `tailor_exercise_set`——读最近的 `KPAssessment`（可能为空）+ material 的 keyphrases 当 fallback whitelist。比之前的 baseline 仍然好（whitelist 用 keyphrases 而不是 None）。

### 单写入路径

`KPMaterial` 和 `KPExerciseSet` 的所有写入都走 `kp.materializer.materialize_kp_material` / `materialize_kp_exercise_set`（UPSERT 语义）。prewarm、tailor、lazy 兜底三个调用方共用。

## Considered Options

- **(A) 保留单表 `KnowledgePointContent`，在 assessor 后强制 bump current_attempt 触发重生成**
  - 优点：schema 改动最小，单 LLM 调用
  - 缺点：每个完成评估的 KP 都要重跑完整 prompt（包括不需要变的 material 部分），token 浪费；attempt 语义被复用（既是"重试"又是"评估后刷新"），未来扩展易乱

- **(B) 单表 + 字段语义区分（`exercises=[]` 表示未生成）**
  - 优点：schema 改动小
  - 缺点：调用方需要靠"字段是否空"分辨状态机，跟"主键是否存在"是两个独立 protocol；可读性差

- **(C) 拆表 + 拆 prompt（本 ADR 选择）**
  - 优点：概念命名清晰；prompt 各自更窄（更省 token，更易调试）；两条生命周期独立演进；validators 也可独立测
  - 缺点：alembic migration 一次；callers 改 schema 引用

## Consequences

### 正面

- 默认 UX 路径就拿到 tailored 题（cache hit 走 `KPExerciseSet`，里面有 covered_concepts）—— 修了静默 bug
- exercise set 重生成不浪费 material tokens；每次 LLM 调用更窄，prompt 调试更聚焦
- `kp.loader` 是纯读侧，`kp.materializer` 是纯写侧，单写入路径 + UPSERT，layer2_snapshot 一致性问题消失
- 测试面：`exercise_layout` / `exercise_validators` / `materializer` 独立模块，validators 可不 mock LLM 直接测

### 负面

- LLM 调用次数 1 → 2 / 完成评估的 KP。但每次 prompt 更小，总 token 成本约持平（材料 prompt 砍掉了 Pro-QuEST 段，exercise prompt 砍掉了 checklist 输出）
- 数据库表多了一张，migration 一次（alembic 0020）
- 学生跳过评估的边缘情况下，tailor 退化为 keyphrases-only whitelist，质量低于走完评估，但仍比拆分前的 baseline 好

### 答辩 / 复盘相关

- "为什么不在 assessor 里直接生成 exercises 省一次 task spawn？"
  - 答：assessor 是同步 endpoint（学生在等评估页渲染），exercise set 生成需要 5-10s LLM 调用，不能拖延 assessor 响应。所以必须异步。
- "tailor 还没跑完学生就点了作业怎么办？"
  - 答：`/content` 同步 fallback 触发 `tailor_exercise_set`——读 `KPAssessment`（已存在）+ material（已存在），生成 tailored 题。等待时间跟 tailor 后台 task 一样 5-10s。前端可以加 loading 态。

## Implementation

| 任务 | 状态 | 关键产出 |
|---|---|---|
| Models 拆分 | 完成 | `KPMaterial` + `KPExerciseSet` 模型；migration 0020 backfill 旧表后 drop |
| Prompts 拆分 | 完成 | `prompts/kp_material.md` + `prompts/exercise_set.md` |
| Materializer | 完成 | `kp/materializer.py`：`generate_kp_material` / `generate_exercise_set` / `materialize_*` / `tailor_exercise_set` |
| Layout / Validators | 完成 | `kp/exercise_layout.py` + `kp/exercise_validators.py`（从 materializer 拆出，独立可测） |
| Prewarm | 完成 | `kp/prewarm.py`（从 `courses/builder.py` 拆出） |
| Assessor 后台触发 | 完成 | `kp/router.py:_spawn_tailor` 在 `post_assessment` 成功后 fire-and-forget |
| Lazy fallback | 完成 | `kp/router.py:get_kp_content` 在 cache miss 时同步调 `tailor_exercise_set` |
| 测试 | 完成 | 155 测试全过；新增 `test_chat_turn.py` 11 个端到端测试 |
| 文档 | 完成 | README + 本 ADR + CONTEXT.md 新增 4 个领域词 |

## References

- 提交：`0de6c35`（拆模型 + 拆 LLM 调用）、`da09317`（内部分层）、`42edfae`（chat→courses 依赖方向修正）
- ADR-0002 / ADR-0013：被本 ADR 取代
- ADR-0019：上一次"对话驱动作业"的设计，本 ADR 实施层落地
- `paper/Pro-QuEST.pdf`：命题原则参照（现在仅 apply 到 exercise_set prompt）
