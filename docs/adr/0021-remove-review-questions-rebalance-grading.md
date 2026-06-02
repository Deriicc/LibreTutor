# 作业模块整修：砍复习题 + 评分加权 + 缓存键修复

## Status

Accepted, 2026-05-15.

Supersedes（部分）:
- ADR-0005（薄弱点反馈：作业混入复习题）——本 ADR 取消"复习题混入"路径；ADR-0005 的"学习报告展示薄弱点"部分保留
- ADR-0015（作业题数量配比、复习题混入与存储策略）——"复习题混入"部分被本 ADR 取消，"数量与存储"部分保留并放宽

Compatible with / refines:
- ADR-0019（对话驱动的作业生成）——本 ADR 不改变 Assessment→Tailor→ExerciseSet 主链
- ADR-0020（KP 内容拆分：KPMaterial vs KPExerciseSet）——本 ADR 在 `KPExerciseSet` 上扩 `difficulty + count` 列，主键不变

## Context

ADR-0019/0020 上线后的作业模块用户实测有四类痛点：

1. **加载/出题等待太长**：`AssessmentPage → ExercisePage` 切换可能阻塞 10-30 秒（material lazy + tailor lazy 双重 LLM 调用）。
2. **评分误导**：`overall_score` 是简单平均；MCQ 0/100 二值波动在 5 题里直接拉低 20 分；复习题虽考前置 KP 却等权计入当前 KP 分数。
3. **retry 流程混乱**：前端把 `advance("retry")` 当缓存失效工具用（仅 `count` 不匹配时触发 bump，污染 attempt 语义；仅改 difficulty 静默失效）。
4. **复习题打断节奏**：尾题跳到前置 KP，注意力被打散；占据题量配额；引入大量 `review_mode / is_review / source_weakness_id` 分支代码与 prompt 段落。

诊断结论：骨架（Material/Assessment/ExerciseSet/Submission/Grade + 异步 tailor/grader）不烂，痛点都是局部的。本 ADR 决定**做局部修整 + 砍复习题**，不彻底重写。

## Decision

### 1. 砍复习题（净简化）

- 删除 `KPExerciseSet.exercises` 里的 `is_review` / `source_weakness_id` / `review_kp_title`（JSONB，无 schema migration）
- 删除 `materializer.pick_review_weakness`、`pick_review_weakness_payload`、`decider.get_weaknesses_before`
- 删除 `generate_exercise_set` 与 `materialize_kp_exercise_set` 的 `review_weakness` 参数；`tailor_exercise_set` 不再调权
- `exercise_layout.layout()` 去掉 `review_mode` 形参；所有 validator 同步去掉 `review_mode`
- 删除 `app.config.review_inject_prob`
- 前端 `Exercise` 类型与 `ExerciseCard` 的"复习题"pill 全部删除

**保留**：`Weakness` 表与 `record_grading_weakness_if_low` / 跳过型 weakness 写入。学习报告页继续展示薄弱点（ADR-0005 的"展示"部分仍生效）。Weakness 池仅服务于报告，不再注入下次作业。

### 2. 缓存键修复：参数化 ExerciseSet

`KPExerciseSet` 增加 `difficulty: str` 和 `count: int` 列（alembic 0021，server_default 'normal'/5，count 从 `jsonb_array_length(exercises)` 回填）。

API 重塑：
- `GET /content` 去掉 `difficulty` / `count` query 参数；纯读 `(kp_id, current_attempt)`；找不到返回 **404**（不再 lazy 触发 tailor）。material lazy 兜底保留，因为它没有 key 冲突。
- **新增** `POST /exercise-set { difficulty, count }`：
  - 命中"已有同参数 row" → 直接返回（assessor 默认预热路径不浪费 LLM 调用）
  - 否则同步调 `tailor_exercise_set` 覆盖该 attempt 的 row
  - 总是返回完整 `KPContentOut`（含 difficulty + count）

`KPContentOut` 增加 `difficulty` 与 `count` 字段，前端"重做一组"按当前题集的参数 regen，不再从 URL 派生。

前端：
- `AssessmentPage.handleStart` 改为 `await postExerciseSet(...)` 之后再 navigate，期间显示"AI 老师正在按你的选择出题…"
- `ExercisePage` 删掉 `advanceKP("retry")` 缓存失效 hack；"重做一组"改为 `advanceKP("retry") + postExerciseSet(...) + setReloadKey`，**不再 `window.location.reload()`**
- 删掉 `AssessmentPage` 的 `sessionStorage` 写入死代码（backend 早已自己 `derive_covered_concepts`）

### 3. 评分加权

> **Update（已撤销，开源版）**：本节的"简答题加权 2 倍"规则已移除，`overall_score`
> 改回**每题等权的算术平均**（`round(Σ score / n)`）。`_GRADE_WEIGHTS` 常量随之删除。
> 下文保留原始决策记录。

`Grade.overall_score` 改为加权平均：

```
weight(mcq) = 1
weight(short_answer) = 2
overall_score = round(Σ score × weight / Σ weight)
```

**Why 加 2 倍**：MCQ 是二值 0/100，单题波动 20 分（5 题集中）；short_answer 是 LLM 连续打分（0-100），更能反映 mastery；不加权时 MCQ 的随机噪声会淹没 short_answer 的信号。常量集中放在 `kp/grader.py` 顶部带说明。

### 4. Weakness 去重

`weaknesses` 加唯一约束 `(user_id, kp_id, source)`（alembic 0021，先 dedup 旧数据后 add constraint）。

新建 `decider.upsert_weakness` 统一两个写入位点（`record_grading_weakness_if_low` 与 `advance("next")` 的 skipped 分支）。冲突时更新 `description` 与 `created_at`（最近一次描述与时间戳）。

### 5. 后台任务韧性

- 已有的 `reset_inflight_submissions`（boot 时把所有 pending/running → failed）保留
- 新增 `reap_stuck_submissions`：周期扫，把 `submitted_at < now() - 5min` 的 pending/running 标 failed。`asyncio.create_task` 在 lifespan 内启动，每 60s 一轮
- 新增 `POST /submissions/{id}/regrade`：仅在 `status=failed` 时允许；重置 status → pending 并 `_spawn_grader`。前端在 `grade_failed` 状态展示"重新批改"按钮

## Considered Options

### 关于"是否彻底重构作业模块"

- **(A) 推倒重写**：表、API、前端全部新设计
  - 优点：可以重新选数据模型
  - 缺点：当前痛点都是局部的（缓存键、加权、weakness 去重），骨架（5 张表 + 异步 tailor/grader）合理；彻底重写收益不大但工作量爆炸
- **(B) 仅砍复习题，其它不动**
  - 优点：最小改动
  - 缺点：四类痛点解决不了三类
- **(C) 局部修整 + 砍复习题（本 ADR 选择）**

### 关于"如何让 difficulty 改动生效"

- **(α) 缓存键扩成 `(kp_id, attempt, difficulty, count)`**：多份并存
  - 缺点：每改一次参数都生成一份，存储和 LLM 都浪费；不需要长期保留旧档
- **(β) 把 difficulty/count 移出缓存键，但写入 row 作为元数据；POST `/exercise-set` 短路（本 ADR 选择）**
  - 优点：assessor 默认预热路径仍有效；用户改参数显式覆盖；attempt 语义干净
- **(γ) 取消 background prewarm，所有人都同步 POST 生成**
  - 优点：协议最简
  - 缺点：每个用户在 AssessmentPage→ExercisePage 切换都阻塞 10-20s

### 关于"评分权重"

- **MCQ:short=1:2（本 ADR 选择）**：常用，足以抵消二值噪声
- **MCQ:short=1:3**：放大 short_answer，但 LLM 短答评分本身有方差，过度依赖会引入新偏差
- **按难度调权**：理论更精细，落地复杂；留待后续 ADR

## Consequences

### 正面

- 复习题相关代码消失（含 ~150 行 `review_mode` 分支 + prompt 指令 + 前端 pill + sessionStorage 死代码）
- AssessmentPage 改 difficulty 后能可靠生效；attempt 重新表达"学生重试次数"
- "重做一组"平滑切换，不再整页 reload
- 加权评分：5 题（3 MCQ 全错 + 2 短答各 80）从 32 → 53 分，更贴近"短答掌握度"
- Weakness 不再随 retry 线性增长；报告页清单稳定
- 卡住的 grader 5 分钟后自动 fail；用户可主动 regrade

### 负面

- 砍复习题失去 ADR-0005 答辩"系统主动复习"卖点；但实际使用中节奏被打断的负面体验更显性
- Weakness 池失去"自动注入下次作业"的功能价值，仅剩"展示"。若后续需要类似主动复习功能，需新 ADR 重新设计（不再用 `pick_review_weakness` 路径）
- 新增 `POST /exercise-set` 与 `POST /submissions/{id}/regrade`，前端协议复杂一档
- `KPExerciseSet` 增 2 列（`difficulty` / `count`），alembic 0021 需要在生产执行

### 不在本 ADR 范围

- `PASS_THRESHOLD` 按难度浮动
- MCQ 答案容错（"A 因为…" 类输入解析）
- `validate_topic_whitelist` 子串匹配的精度
- 学习报告页对 Weakness 的展示形式
- KPMaterial lazy 同步在 `/content` 的体感问题（prewarm 已基本兜住）

## Implementation

| 任务 | 状态 | 关键产出 |
|---|---|---|
| 砍复习题（backend） | 完成 | materializer / exercise_layout / exercise_validators / decider / config / prompts |
| 砍复习题（frontend） | 完成 | api/kp.ts、api/report.ts、ExercisePage、AssessmentPage |
| Cache key 修复 | 完成 | KPExerciseSet 增列；`POST /exercise-set`；前端 `postExerciseSet` |
| 评分加权 | 完成 | grader.py `_GRADE_WEIGHTS` |
| Weakness 去重 | 完成 | weakness.py 唯一约束；`decider.upsert_weakness` 统一写入 |
| 后台韧性 | 完成 | `reap_stuck_submissions` 周期任务；`POST /submissions/{id}/regrade`；前端 `grade_failed` 状态 |
| Alembic 0021 | 完成 | KPExerciseSet 加列 + Weakness 唯一约束（含 dedup） |
| 测试 | 进行中 | 删除 review_mode 用例；新增加权、upsert、reaper、regrade 测试 |

## References

- 提交：本次改造批次（branch `main`，2026-05-15）
- ADR-0005 / ADR-0015：复习题部分被本 ADR 取代
- ADR-0019 / ADR-0020：主链与本 ADR 兼容
- Plan：`/home/derick/.claude/plans/elegant-snuggling-fountain.md`
