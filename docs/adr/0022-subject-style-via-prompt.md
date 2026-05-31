# 学科适配走 prompt 工程，不进 schema

## Status

Accepted, 2026-05-15.

Compatible with / refines:
- ADR-0014（Pro-QuEST 命题原则）——本 ADR 在 mcq 题型选择上叠加"学科偏好"软引导
- ADR-0020（KPMaterial vs KPExerciseSet 拆分）——本 ADR 不动 schema，只改两份 prompt
- ADR-0021（砍复习题 + 局部修整）——本 ADR 是其测试后的后续修整

## Context

实测发现作业模块在不同学科上输出风格雷同——数理 KP 也给出大量 Interpretation / Comparison 类题，文科 KP 也强行套用 Quantification 框架。`prompts/exercise_set.md` 与 `prompts/kp_material.md` 都只讲 Pro-QuEST 12 类题型与命题原则，未告知 LLM"根据学科调整题型偏好"。

考虑的方案：
- **(A) Course 加 `subject_kind` 字段**：上传时选/或首页选；prompt 路由分文/理/工/史…
- **(B) 抽取书中已有习题作为题源**：PDF 题目段落分割 + KP 边界对齐 + 参考答案推断；高质量但重活
- **(C) 只在 prompt 里加学科自适应段，让 LLM 从 PDF 自己识别学科**

## Decision

**采用 (C)**。理由：

1. PDF 文本已经在每次 prompt 输入里，LLM 完全有能力推断学科——缺的只是"被告知要做这件事"
2. (A) 引入 schema migration、上传 UI、course-level 状态机；用户每门课要多一次选择动作；与"用户应不做教学决策"的方向矛盾
3. (B) 是单独一个项目级别的工作，与本轮范围不符
4. (C) 风险可控：学科适配是软引导，最终题型仍受 Pro-QuEST 12 类清单 + 难度档锁定 + question_type 互不相同约束兜底；LLM 偏离时不会破坏输出契约

## Implementation

- `prompts/exercise_set.md` 新增"学科自适应"段：列举 5 个学科大类与各自的 mcq 题型偏好（数理偏 Quantification / Procedure / Causal；人文偏 Interpretation / Comparison / Contradiction）
- `prompts/kp_material.md` 新增"学科判读"段：keyphrases 与 knowledge_checklist description 的措辞风格按学科调整
- 不改 schema、不加 backend 字段、不加 frontend UI

## Consequences

### 正面
- 零 schema 改动；可立即上线
- 同一份 PDF 不论数理还是人文，输出风格更贴近学科
- 后续若需更精细控制（如教材层级），可平滑过渡到 (A)

### 负面
- LLM 软约束失效时输出仍可能跑偏；现有 max_retries=1 兜底，若失败率显著上升可加大重试
- 不抽书中习题意味着 KP 题目仍 100% LLM 生成；如教材本身有高质量习题不会被利用——留待 (B) 单独立项
- 没有"主题强度"调节旋钮：用户没办法说"这门课请按理工处理"

## Considered Options（详）

- (A) subject_kind 字段：
  - 优点：路由清晰，可针对学科写专用 prompt
  - 缺点：迁移成本、UI 成本、学生需做决策
- (B) 抽书中习题：
  - 优点：题目质量最高，与课本完全一致
  - 缺点：实现复杂（OCR + 段落分类 + KP 对齐 + 答案推断），单独立项
- (C) Prompt 自适应（本 ADR 选择）

## References

- ADR-0014 / ADR-0020 / ADR-0021
- 实测反馈：本轮 plan 的 Issue 3
- 修改的 prompt：`backend/app/prompts/exercise_set.md`、`backend/app/prompts/kp_material.md`
