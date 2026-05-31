---
status: accepted
---

# Attempt 隔离：聊天分轮 + 日记进度口径修正

`KPAssessment`、`KPExerciseSet`、`Submission`、`TeacherDiaryEntry` 都已经按 attempt 建模，但 `Message` 之前只有 `kp_id`。retry 后，新一轮 assessment/diary/activity guard 会读到旧轮对话，导致 coverage 虚高、日记失真、空的新 attempt 被误判为"有教学活动"。

同一批修正也收紧了日记 `_compute_progress` 的 completion 口径：合成的全书导读/总结 KP 是只读且永不 passed，不能拖低完成度。

## Decision

### 1. `Message` 增加 `attempt`

- `messages.attempt INTEGER NOT NULL DEFAULT 1`
- 旧消息 backfill 为 attempt 1；历史上真实分轮不可恢复，接受。
- 新增索引 `(kp_id, attempt, created_at)`，服务当前主查询：某 KP 某 attempt 按时间读对话。

### 2. 写入时捕获 attempt

Chat route 在请求开始时读取 `kp.current_attempt` 并保存到局部变量：

- user message 写这个 attempt。
- LLM history 只查这个 attempt。
- assistant message 在 SSE 结束后另开 session 写入，但仍使用捕获的 attempt。

原因：SSE 期间用户可能点击 retry，`current_attempt` 会被 bump；assistant 回复必须留在它实际回答的那一轮。

### 3. 所有教学读点按 attempt 过滤

- chat list/opening：只看当前 attempt。
- assessor history：只看 `(kp_id, attempt)`。
- diarist inputs：只看 `(kp_id, attempt)`。
- `_attempt_has_activity`：只看当前 attempt 的 message 或 submission。

因此 retry 是干净的新轮；旧轮数据保留在旧 assessment/exercise/submission/diary 中，不污染新轮。

### 4. 日记 progress 只统计可完成 KP

`courses.report._compute_progress` 是喂给 diarist 的事实聚合。它现在与课程卡片/admin 一致：

- `kp_total/kp_passed` 排除 `boundary.kind in {"overview","summary"}` 的合成 KP。
- chapter passed/total 的 rollup 同样排除合成 KP。

这修复"课程卡片 100%，日记里却 N/M 永远不到 100%"的矛盾。

### 5. 学习时长按 `(kp_id, attempt)` 分组

旧算法按 `kp_id` 求 `max(created_at)-min(created_at)`。如果 attempt 1 周一聊、attempt 2 周五聊，中间空档会被算成学习时长。

新算法按 `(kp_id, attempt)` 分组后求和，避免 retry 之间的死时间进入 `study_minutes`。

注意：`study_minutes` 仍包含全书导读/总结聊天时间。这是产品定义：completion 只统计学习闭环内的 KP；study time 统计学生真实与老师互动的时间。不要把它归为完成度 correctness bug。

## Consequences

- 当前 chat pane retry 后只展示当前 attempt；旧对话通过 diary/history 数据留存，不混进当前教学流。
- 对话、评估、题集、提交、日记现在共享同一 attempt 边界。
- 后续如果要展示旧 attempt 对话，需要显式做 attempt 切换器，而不是恢复 `kp_id` 全量查询。
- completion 与章节状态必须继续使用"可完成 KP"口径；合成 KP 不参与过关数学。
- study_minutes 是粗略上界：同一 attempt 内的长时间 idle 仍不会被扣除。
