# 对话驱动的作业生成（assessment-mediated exercise generation）

## Status

Accepted, 2026-05-14. Supersedes the implicit "exercise generation reads only PDF text" assumption that was not previously formalized as an ADR. Compatible with ADR-0014 (Pro-QuEST principles), ADR-0016 (三层 prompt), ADR-0018 (上下文管理).

**Refined by ADR-0020**（2026-05-14）：本 ADR 的核心决策（评估驱动作业生成）保留，但实施层落地从"单 `generate_kp_content` 调用 + `covered_concepts` 入参"改为"拆 `KPMaterial` / `KPExerciseSet` 两表 + `kp.materializer.tailor_exercise_set` 在 assessor 后异步 fire-and-forget"。下方 Implementation 表里的 `generate_kp_content` / `KnowledgePointContent` 引用已过期——当前的代码符号请见 ADR-0020。

## Context

Issue 25 surfaced two related problems with the original "对话 → 作业" link:

1. **对话本身退化为无限追问**。`socratic_layer1.md` 的"永远不主动给定义/公式/答案" + "每轮 1-3 句话" 让 LLM 的最优策略是只问不答，知识密度低。学生主观感觉"聊很多但没学到"。
2. **作业生成完全不读对话历史**。`generate_kp_content(kp_title, pdf_path, page_start, page_end)` 入参里没有学生在对话中实际讨论的概念。结果作业可能：
   - 出对话没讲到的题
   - 难度恒定 5 道，与学生掌握程度无关
   - 没有"这一轮该简单还是该难"的判断依据

ADR-0004（"系统给建议、用户决定"）确立了系统不应硬卡学生。ADR-0014 借鉴 Pro-QuEST 但没规定"出题前先读对话"。ADR-0016 设计意图里有"每 5 轮内部判断是否结束"，但代码只实现了 20 轮硬触发软上限。

## Decision

新增**对话→评估→作业**三段链路：

```
[对话端]                [评估端]            [作业端]
Layer 1 四阶段教学  →  POST /assessment  →  GET /content?difficulty=X&count=Y
Layer 3 知识地图       LLM 一次性输出       覆盖度硬约束 + 难度档题型 + 动态题量
                       coverage/mastery
```

### 1. 对话端：Layer 1 引入"诊断 → 引导 → 锚定 → 迁移"四阶段

- 删除"永远不主动给定义"绝对句，改为分阶段规则
- **锚定阶段**强制要求：4-6 句话 + 定义 + 公式（LaTeX）+ 一个例子；触发条件 = 学生接近正确 / 连续两次答错 / 引导徘徊 5 轮以上
- 每 5 轮元指令"自查阶段"——防止退化
- 每个 KP 至少经历一次锚定阶段
- few-shot 示例从 6 段扩到 7 段（新增锚定示例）

### 2. KP 内容生成增加 `knowledge_checklist`

- 每项 `{concept, description, must_anchor: bool}`，3-7 项
- 至少 2 项 must_anchor=true（必须经过锚定）
- 在 Layer 3 中以"★"标记带入 system prompt

### 3. 评估端：新模型 + 新 endpoint

- `KPAssessment` 表，复合主键 `(kp_id, attempt)`
- prompt 输入对话历史 + checklist；输出 covered/partial/untouched + coverage_ratio + mastery_summary + suggested_difficulty + suggested_count
- 严格校验：每个 checklist 概念**恰好**出现在三栏之一，不漏不多不重
- 空 history 或空 checklist → 走 fallback（不调 LLM，返回 0% 覆盖度的空 assessment）

### 4. 作业端：参数化 + 硬约束

- `generate_kp_content` 增加 `covered_concepts` / `difficulty` / `count`
- 题目题干必须含 covered_concepts 中至少一个子串（`_validate_topic_whitelist`）
- 难度档锁定题型分布（`DIFFICULTY_TYPE_MIX`）：
  - easy: Definition / Example / Application
  - normal: 自由（保持原 distinct-types 规则）
  - hard: Comparison / Causal Consequence / Inference
- 题量动态 [2, 7]：count<5 时不混复习题；count>=5 时最后 1 道可改复习

### 5. 前端串联

- 新页面 `AssessmentPage`：覆盖度环形图 + 三栏概念列表 + 难度 radio + 题量 stepper
- 覆盖度 < 60% 显示红字警告 + confirm 弹框，但允许"硬上"（ADR-0004 精神）
- KPPage 的"我懂了，做题去"按钮跳转到 `/assessment` 而不是 `/exercise`
- ExercisePage 检测 cache count mismatch → 自动调 `advanceKP("retry")` bump attempt

### 6. 评估的 attempt 跨域复用

- 评估写 `(kp_id, current_attempt)`
- 作业出题时查 covered_concepts 用 `ORDER BY attempt DESC LIMIT 1`，不限 attempt
- 理由：对话历史本身跨 attempt 不变，所以旧 attempt 的评估对新 attempt 仍有效

## Considered Options

### Option A：在对话过程中实时维护"已覆盖概念" 状态机（拒绝）

每轮对话后让 LLM 标注当前阶段 + 已讨论概念 → DB 状态表。

- 优点：评估时不用再读对话历史，直接读状态表
- 缺点：每轮多一次 LLM 调用，延迟翻倍；ADR-0014 已明确反对（"prompt chain 三步法"）
- 决策：拒绝。改为评估时一次性读全部对话历史。

### Option B：作业生成不读对话，靠学生在前端"自我评估"（拒绝）

让学生自己勾选"我觉得我懂哪些"，作为出题白名单。

- 优点：不调 LLM
- 缺点：学生倾向高估自己的掌握程度，作业难度系统性偏简单
- 决策：拒绝。改为 LLM 评估为主，学生可调（前端 radio + stepper）。

### Option C：评估改在对话最后一轮自动嵌入 system prompt（拒绝）

学生说"我懂了"时，让最后那次对话 LLM 调用顺便输出评估 JSON。

- 优点：节约一次 LLM 调用
- 缺点：让对话 LLM 同时承担"老师"和"评估员"两个角色，角色混乱；输出格式（自然语言 vs JSON）冲突
- 决策：拒绝。评估单独一次调用，逻辑清晰。

### Option D：硬约束 covered_concepts 改成软约束（拒绝）

允许作业出 covered 之外的题，前端标"延伸题"。

- 优点：作业能测迁移能力
- 缺点：用户明确说"作业可能会显得过于简单，有时候会出现上课没有讲到的内容"——抱怨的就是这个
- 决策：拒绝。硬约束。如果以后需要"延伸题"，可以加 `extension_concepts` 列表单独控制。

## Consequences

### 正面

- 学生主观感觉"对话有节奏"——锚定阶段是知识真正落地的环节
- 作业题目永远在"已讨论"范围内，不会突袭
- 学生能根据自己感觉调难度和题量
- 三段都有独立的 LLM 调用 + 独立的 DB 表（`KnowledgePointContent` / `KPAssessment`），可以分别迭代

### 负面

- 多了一次 LLM 调用（评估），延迟从"对话→作业 ~3s" 变成"对话→评估 ~3s + 评估→作业 ~3s"
- 缓解：评估页本身是教学反馈，能让 6s 等待感觉值得
- DB 表多了一个，schema 演进成本上升
- LLM 评估结果可能与学生自我感受不一致——但前端允许学生覆盖

### 答辩相关

- 答辩可能问："为什么不用更轻量的关键词匹配代替 LLM 评估？"
  - 答：关键词匹配无法判断"理解程度"——学生说"导数就是斜率"和"导数是 lim_{h→0} ..."，关键词都命中"导数"，但理解深度不同。LLM 能区分。
- 答辩可能问："硬约束会不会让作业太窄？"
  - 答：覆盖度低时题量也低（max(2, round(ratio*5))），"窄而少"比"宽而瞎"更尊重学生当前的学习状态。
- 答辩可能问："评估失败怎么办？"
  - 答：assessor 校验失败时 endpoint 返回 502，前端有重试按钮。空对话/空 checklist 走 fallback，不影响主流程。

## Implementation

| 任务 | 状态 | 关键产出 |
|---|---|---|
| Task 1 | 完成 | `socratic_layer1.md` 重写（78 行）+ Sakiko 版 + persona few-shot 7 段 |
| Task 2 | 完成 | `knowledge_checklist` JSONB 列 + alembic 0017 + Layer 3 注入 |
| Task 3 | 完成 | `KPAssessment` 模型 + alembic 0018 + `kp/assessor.py` + `POST /assessment` |
| Task 4 | 完成 | 前端 `AssessmentPage` + 路由 + 覆盖度环形图 |
| Task 5 | 完成 | `generate_kp_content` 增加 `covered_concepts`/`difficulty`/`count` + 硬约束 validator |
| Task 6 | 完成 | `DIFFICULTY_TYPE_MIX` + 题型按位置硬校验 |
| Task 7 | 完成 | `_layout(count, review_mode)` 函数化 + count 范围 [2,7] |
| Task 8 | 完成 | 前端 ExercisePage 读 URL query + attempt bump 逻辑 |
| Task 9 | 完成 | e2e 测试 6 个 + 失败模式文档 + 本 ADR |

## References

- ADR-0014：Pro-QuEST 命题原则
- ADR-0016：三层 prompt 架构
- ADR-0018：上下文管理
- `assets/dialogue_to_exercise_failure_modes.md`：链路上的已知失败模式
- `assets/chat_dialogue_independent_review.md`：实施前对旧链路的代码审阅（独立分析）
- `assets/low_knowledge_density_analysis.md`：实施前对"对话密度低"的根因分析
- `paper/Pro-QuEST.pdf` / `paper/DeepTutor TowardsAgentic Personalized Tutoring.pdf`：方法论参照
