# 作业编辑器：富文本 + 公式输入

作业编辑器采用富文本 + 公式输入支持。编辑器选 TipTap / Quill 等成熟方案；公式输入用 MathLive 或类似 WYSIWYG 组件，渲染用 KaTeX / MathJax。

支持目标：通用学科自学场景（数学、物理、化学等需要公式的题型）。

## Considered Options

- **纯 textarea**：实现极简，但限于纯文字题型，与"通用学科"定位冲突。
- **LaTeX 源码 + KaTeX 渲染（无 WYSIWYG）**：折中方案，工时减半，但要求学生会 LaTeX 语法。

## Consequences

- 多 3-5 天工作量：富文本编辑器集成（1.5-2 天）+ MathLive 集成（1-2 天）+ LLM 评分对 HTML/Markdown/LaTeX 输入的适配（0.5-1 天）。
- 演示场景下学生可写公式、富文本作答，"通用学科"的定位有真实支撑。
- LLM 评分 prompt 需要适配富文本结构化输入；学生写错 LaTeX 语法的兼容处理需要明确规则。
- 应急砍功能时降级到 LaTeX 源码 + KaTeX 渲染（无 WYSIWYG），可省 2-3 天。
