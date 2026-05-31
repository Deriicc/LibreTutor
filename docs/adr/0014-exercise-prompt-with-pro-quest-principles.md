# 作业题生成：内嵌 Pro-QuEST 原则的混合题型 prompt

每个 **KnowledgePoint** 进入时（参见 ADR-0013），LLM 一次调用同时生成讲解材料 + 作业题。作业生成的 prompt **内嵌借鉴 Pro-QuEST (Gollapalli et al., EACL 2026) 的方法论**，但不照搬全流程：

- **Document-grounded (P2)**：题目必须基于提供的 KP 文本片段；prompt 明确禁止引用文档外知识。
- **Keyphrase-driven (P3)**：prompt 要求 LLM 先识别本 KP 的 keyphrase（3-5 个），每道 MCQ 围绕一个 keyphrase。
- **Question Type Taxonomy (P4)**：MCQ 题型从 Pro-QuEST 12 类中选取多种（Definition / Comparison / Causal Consequence / Quantification / Interpretation 等），保证题型多样性。
- **混合题型（与 Pro-QuEST 不同）**：每次作业包含 MCQ + 简答题（具体数量配比由 ADR 后续实例化）。

**不照搬** Pro-QuEST 的 prompt chain 三步法（P1）—— 单 KP 文本片段不需要分阶段处理，否则进入延迟翻倍。
**不限于** Pro-QuEST 的纯 MCQ 题型（P5）—— 学生自学场景需要简答/分析题型，富文本编辑器（ADR-0011）才有意义。

## Considered Options

- **照搬 Pro-QuEST prompt chain（β）**：进入 KP 多次 LLM 调用，延迟从 1-3 秒拉到 4-8 秒。Pro-QuEST 为长文档（整本教材）设计；单 KP 文本片段不需要。
- **完全脱离 Pro-QuEST 自由生成**：放弃论文学术参照，缺失答辩论证抓手。

## Consequences

- 作业题质量高度依赖 prompt 质量；需要重点调试（few-shot 示例 + question type 注入）。
- Pro-QuEST 论文承认 LLM 生成题目 easy 率（30-40%）显著高于专家命题（10-16%），需要在论文/答辩中诚实引用为已知局限。
- 答辩可能被问"Pro-QuEST 是企业培训场景，你借鉴是否合理"，备好回答：借鉴 P2/P3/P4，适配学生学习场景并扩展到混合题型 + 教学循环对接。
- MCQ 与简答题的 LLM 评分逻辑不同，需要**两套评分 prompt**。
- 题型配比 + 复习题混入参数等具体数值由 C.子-3/4/5 决定。
