// Lightweight i18n: the Chinese source string is the key. `t(zh)` returns
// the Chinese key as-is in zh mode, or its English translation (falling back
// to the key) in en mode. Add entries here as strings are wrapped in t().

/** Standalone translator for non-component modules (api clients). Reads the
 * stored language directly. Keep the storage key in sync with LanguageContext. */
export function currentLang(): "zh" | "en" {
  const s =
    typeof localStorage !== "undefined"
      ? localStorage.getItem("libretutor.lang")
      : null;
  return s === "en" ? "en" : "zh";
}

export function et(zh: string, vars?: Record<string, string | number>): string {
  const stored =
    typeof localStorage !== "undefined"
      ? localStorage.getItem("libretutor.lang")
      : null;
  let s = stored === "en" ? EN[zh] ?? zh : zh;
  if (vars) {
    for (const k of Object.keys(vars)) {
      s = s.split(`{${k}}`).join(String(vars[k]));
    }
  }
  return s;
}

export const EN: Record<string, string> = {
  // ---- common / actions ----
  "保存": "Save",
  "保存中…": "Saving…",
  "删除": "Delete",
  "删除中…": "Deleting…",
  "取消": "Cancel",
  "返回": "Back",
  "返回书房": "Back to library",
  "加载中…": "Loading…",
  "加载失败": "Failed to load",
  "保存失败": "Save failed",
  "删除失败": "Delete failed",
  "创建失败": "Create failed",
  "重试": "Retry",
  "新建": "New",
  "上传": "Upload",
  "设置": "Settings",

  // ---- KP status ----
  "未学": "Not started",
  "学习中": "In progress",
  "已掌握": "Mastered",
  "未开始": "Not started",
  "通过": "Passed",

  // ---- generation status ----
  "等待中": "Pending",
  "生成中": "Generating",
  "生成中…": "Generating…",
  "加载完成": "Ready",
  "失败": "Failed",
  "生成失败": "Generation failed",

  // ---- nav / breadcrumbs ----
  "章节树": "Chapter tree",
  "对话": "Dialogue",
  "教师手记": "Teacher diary",
  "角色卡": "Persona",
  "作业": "Exercises",
  "课程": "Course",
  "菜单": "Menu",

  // ---- home ----
  "欢迎回来": "Welcome back",
  "我的课程": "My courses",
  "新建一门课": "New course",
  "上传一份新资料": "Upload new material",
  "PDF · 支持目录解析": "PDF · outline parsing supported",
  "生成章节树": "Builds a chapter tree",
  "个知识点": "KPs",
  "节": "sections",
  "确定删除「{name}」？此操作不可恢复。":
    'Delete "{name}"? This cannot be undone.',

  // ---- settings ----
  "语言": "Language",
  "界面语言；新建课程的章节树、对话与出题也会使用该语言。":
    "UI language; new courses' chapter tree, dialogue, and exercises will use it too.",
  "系统不再提供公用 Key —— 对话、评分、评估、日记、课程构建均使用你在此填写的 API。未配置 Chat 时这些功能不可用。":
    "There is no shared key — dialogue, grading, assessment, diary, and course building all use the API you enter here. Without a Chat key these features won't work.",
  "对话模型（Chat）": "Chat model",
  "接口格式": "API format",
  "OpenAI 兼容": "OpenAI-compatible",
  "Anthropic 兼容": "Anthropic-compatible",
  "两者都通过 OpenAI 兼容客户端调用；选 Anthropic 时请把 Base URL 指向其 OpenAI 兼容代理。":
    "Both are called via the OpenAI-compatible client; for Anthropic, point Base URL at its OpenAI-compatible proxy.",
  "模型": "Model",
  "测试中…": "Testing…",
  "测试连通性": "Test connection",
  "测试失败": "Test failed",
  "向量模型（Embedding）": "Embedding model",
  "可选。留空则用本地哈希向量降级（检索更粗糙，但不依赖外部 Key）。":
    "Optional. Leave blank to fall back to local hash embeddings (coarser retrieval, but no external key needed).",
  "保存设置": "Save settings",
  "已保存": "Saved",

  // ---- create course ----
  "新建课程": "New course",
  "上传一份学习资料": "Upload study material",
  "课程名称": "Course name",
  "例如：计算机网络期末复习": "e.g. Computer Networks final review",
  "松手放下": "Drop to upload",
  "把 PDF、EPUB 或 Markdown 拖到这里": "Drag a PDF, EPUB, or Markdown here",
  "或点击选择文件 · 支持 .pdf / .epub / .md / .markdown · 上限 50 MB":
    "or click to choose a file · .pdf / .epub / .md / .markdown · up to 50 MB",
  "仅支持 .pdf / .epub / .md / .markdown 文件":
    "Only .pdf / .epub / .md / .markdown files are supported",
  "请选择文件": "Please choose a file",
  "上传中…": "Uploading…",
  "创建课程": "Create course",
  "章节树将基于你的目录": "The chapter tree follows your table of contents",
  "系统抽取 PDF outline 作为章/节骨架，再让 LLM 把每一节切分成 1–3 个聚焦单一概念的 KP。":
    "We extract the PDF outline as the chapter/section skeleton, then let the LLM split each section into 1–3 focused knowledge points.",
  "生成所需时间根据文本长度决定": "Generation time depends on the text length",
  "期间会同时切片 PDF 并建立向量索引。可以离开页面，完成后会自动刷新。":
    "Meanwhile the PDF is chunked and a vector index is built. You can leave the page; it refreshes when done.",
  "章节树生成后不可改": "The chapter tree is immutable once built",
  "如对结果不满意，可以重新上传以重建。这是为了保证学习路径的稳定性。":
    "If you're unhappy with the result, re-upload to rebuild. This keeps the learning path stable.",

  // ---- assessment ----
  "覆盖度": "Coverage",
  "（无）": "(none)",
  "评估失败": "Assessment failed",
  "学习评估": "Learning assessment",
  "课程评估结果": "Assessment result",
  "正在翻看你和老师的对话…": "Reviewing your conversation with the teacher…",
  "← 返回对话": "← Back to dialogue",
  "老师的判断": "The teacher's judgment",
  "覆盖不足": "Insufficient coverage",
  "：建议先回到对话，重点聊一下「未触及」清单里的概念，再来做作业。":
    ": go back to the dialogue and focus on the “untouched” concepts before doing the exercises.",
  "部分掌握": "Partially mastered",
  "未触及": "Untouched",
  "简单档": "Easy",
  "困难档": "Hard",
  "正常档": "Normal",
  "← 返回继续学习": "← Back to learning",
  "开始作业 →": "Start exercises →",
  "老师将按本次掌握情况自动出 {n} 道题":
    "The teacher will auto-generate {n} questions based on this session",
  "对话覆盖度只有 {pct}%，作业题量已自动减少。\n\n确认要直接进入作业吗？也可以选择「返回继续学习」":
    "Dialogue coverage is only {pct}%; the question count has been reduced automatically.\n\nProceed to the exercises anyway? You can also go back to keep learning.",

  // ---- course page ----
  "只读：可与老师对话，不计入进度":
    "Read-only: you can chat with the teacher, but it doesn't count toward progress",
  "总结": "Summary",
  "导读": "Overview",
  "正在誊抄章节树": "Transcribing the chapter tree",
  "本阶段": "Current stage",
  "每 {n} 秒自动刷新 · 全程约 5~8 分钟 · 可离开页面":
    "Auto-refreshes every {n}s · about 5–8 min total · you can leave the page",
  "Course 不存在或无权访问": "Course not found or not accessible",
  "章节骨架尚未落定…": "The chapter skeleton isn't settled yet…",
  "课程已就绪": "Course ready",
  "正在生成章节树…": "Generating the chapter tree…",
  "等待生成": "Waiting to generate",
  "个 KP": "KPs",
  "已完成": "Done",
  "章节树生成失败": "Chapter tree generation failed",
  "未知错误": "Unknown error",
  "继续从这里学": "Continue from here",
  "继续对话 →": "Continue dialogue →",
  "跳到作业": "Skip to exercises",
  "章节进度概览": "Chapter progress overview",
  // generation stages
  "解析目录": "Parsing outline",
  "切分知识点": "Splitting knowledge points",
  "落定章节": "Settling chapters",
  "纸册之上，先识其骨。": "On the page, first know its bones.",
  "系统正在阅读 PDF 文本，由 LLM 推断章节骨架——":
    "Reading the PDF text and inferring the chapter skeleton with the LLM —",
  "目录决定我们的学习路径": "the outline determines our learning path",
  "目录已知，章节小节皆已就位。": "The outline is known; chapters and sections are in place.",
  "现在为每一节切出 1~3 个聚焦单一概念的知识点，":
    "Now splitting each section into 1–3 focused knowledge points,",
  "多节并发处理，互不阻塞": "processed concurrently, without blocking each other",
  "知识点已就位。": "The knowledge points are in place.",
  "正在装订成册——稍候片刻即可进入学习。":
    "Binding it into a book — a moment more and you can start learning.",

  // ---- editor + api errors ----
  "提示：支持 Markdown 与数学公式。行内公式 $...$，块级 $$...$$。":
    "Tip: Markdown and math are supported. Inline $...$, block $$...$$.",
  "预览": "Preview",
  "加载消息失败 (HTTP {status})": "Failed to load messages (HTTP {status})",
  "流式读取异常": "Streaming error",
  "网络错误": "Network error",
  "请求失败 (HTTP {status})": "Request failed (HTTP {status})",
  "加载日记失败 (HTTP {status})": "Failed to load the diary (HTTP {status})",

  // ---- exercise page ----
  "翻看课本…": "Flipping through the book…",
  "斟酌题目…": "Pondering the questions…",
  "誊写题面…": "Writing them out…",
  "首次约 10–20 秒": "First time takes ~10–20 s",
  "✓ 答对": "✓ Correct",
  "△ 待加强": "△ Needs work",
  "✗ 答错": "✗ Wrong",
  "选择题": "Multiple choice",
  "简答题": "Short answer",
  "老师评语": "Teacher's comment",
  "参考答案：": "Reference answer: ",
  "提交失败": "Submission failed",
  "评分失败": "Grading failed",
  "查询批改状态失败": "Failed to check grading status",
  "重新批改失败": "Re-grading failed",
  "操作失败": "Operation failed",
  "← 回到对话": "← Back to dialogue",
  "{n} 道选择": "{n} multiple choice",
  "{n} 道简答": "{n} short answer",
  "{total} 道题 · {parts}": "{total} questions · {parts}",
  "加载题目中…": "Loading questions…",
  "AI 老师正在批阅…": "The AI teacher is grading…",
  "异步进行 · 每 {n} 秒自动刷新": "Runs asynchronously · auto-refreshes every {n}s",
  "① MCQ 比对": "① MCQ matching",
  "② 简答 LLM 评分": "② LLM scoring of short answers",
  "③ 综合判定": "③ Final judgment",
  "批阅失败": "Grading failed",
  "重新批改": "Re-grade",
  "已提交": "Submitted",
  "重做一组（生成新题）": "Redo a set (new questions)",
  "下一个 KP →": "Next KP →",
  "已作答": "Answered",
  "提交作业": "Submit",

  // ---- diary book ----
  "老师": "Teacher",
  "师": "T",
  "翻开日记本…": "Opening the diary…",
  "日记本还是空的。": "The diary is still empty.",
  "等老师在第一节课后落笔，这里就会有第一篇。":
    "Once the teacher writes after the first lesson, the first entry will appear here.",
  "A Teacher's Journal · 教师手记": "A Teacher's Journal",
  "每一节课结束后，老师在这本日记里写下当晚的复盘。":
    "After each lesson, the teacher writes that evening's reflection in this diary.",
  "篇已成稿": "written",
  "共 {n} 位执笔人": "{n} author(s) in all",
  "编年索引": "Chronological index",
  "· 未提笔": "· not yet written",
  "复盘": "Reflection",
  "第 {n} 次执笔": "Written for the {n}th time",
  "retry · 第 {n} 次": "retry · #{n}",
  "第 {n} 篇": "No. {n}",
  "关于「{title}」": "On “{title}”",
  "— 这是我在这本日记里的最后一笔。":
    "— This is my last entry in this diary.",
  "— {date}　灯下记。": "— {date}, written by lamplight.",
  "上次没写完，老师稍后会回来补上这一笔。":
    "It was left unfinished last time; the teacher will come back to complete it.",
  "今夜尚未提笔——老师还在桌前推敲措辞。":
    "Not yet written tonight — the teacher is still at the desk weighing the words.",
  "这一节她还在路上。等这堂课结束，{author}会回到桌前，把今晚的事写下来。":
    "This lesson is still underway. Once it ends, {author} will return to the desk and write down tonight's events.",
  "对话进行中": "Dialogue in progress",
  "今夜尚未提笔。": "Not yet written tonight.",
  "预计执笔　·　{author}": "To be written by　·　{author}",
  "边 · 注": "Margin · notes",
  "此刻": "Right now",
  "上次写到一半搁笔了。": "It was left half-written last time.",
  "老师正在写这一篇…": "The teacher is writing this entry…",
  "这一节还没落笔。": "This entry hasn't been started yet.",
  "等她说出“好像懂了”，今晚的日记才会开始写。":
    "Once she says “I think I get it,” tonight's diary will begin.",
  "返回主页": "Back to home",
  "返回该章节": "Back to this section",
  "上一篇": "Previous",
  "下一篇": "Next",
  "第": "No.",
  "篇 / 共 {n} 篇": " / {n} total",
  "翻页": "Turn page",

  // ---- KP dialogue page ----
  "当前所在 KP": "Current KP",
  "软上限 {n}": "Soft cap {n}",
  "你的消息": "Your message",
  "导师消息": "Tutor's message",
  "导师": "Tutor",
  "老师正在备课": "The teacher is preparing",
  "全书总结": "Book Summary",
  "全书导读": "Book Overview",
  "翻到新一页…": "Turning to a new page…",
  "老师正在准备这一节的内容": "The teacher is preparing this section",
  "当前位置": "Current location",
  "← 返回章节树": "← Back to chapter tree",
  "第 {n} 轮 · {status}": "Round {n} · {status}",
  "只读 · {label} · 仅对话": "Read-only · {label} · chat only",
  "我懂了，去做题 →": "I get it — start exercises →",
  "重新发送": "Resend",
  "写下你的想法，哪怕只是猜测… (CTRL + ↵ 发送)":
    "Write your thoughts, even just a guess… (CTRL + ↵ to send)",
  "发送": "Send",
  "对话状态": "Dialogue status",
  "本节预计": "Estimated for this section",
  "15 分钟": "15 min",
  "当前轮次": "Current round",
  "如果你 …": "If you …",
  "累了，休息一下": "Tired, take a break",
  "返回章节树，进度已保存": "Back to the chapter tree; progress is saved",
  "跳过对话，做作业": "Skip the dialogue, do exercises",
  "未通过则进入薄弱点": "If you don't pass, you'll focus on weak spots",
  "这节课的关键词": "Keywords for this lesson",

  // ---- teacher config (persona) page ----
  "比如：\n你是理查德·费曼，加州理工的物理学教授。你最擅长把复杂概念拆成最朴素的大白话，喜欢用第一性原理和生活化的例子来讲解，绝不堆砌术语。你风趣、直率、充满好奇心，常常反问学习者\"那你觉得为什么会这样？\"来引导他自己想明白。":
    "e.g.\nYou are Richard Feynman, a physics professor at Caltech. You're best at breaking complex ideas into the plainest everyday language, you love explaining with first principles and real-life examples, and you never pile on jargon. You're witty, blunt, and endlessly curious, often turning a question back on the learner — \"So why do you think that happens?\" — to lead them to work it out themselves.",
  "比如：\n大二物理系学生，对量子力学零基础，5 月底前要掌握薛定谔方程的物理图像。我喜欢用类比和具体例子来理解抽象概念。":
    "e.g.\nA sophomore physics student with zero background in quantum mechanics, who needs to grasp the physical picture of the Schrödinger equation by the end of May. I like to understand abstract concepts through analogies and concrete examples.",
  "正在为 TA 写台词…": "Writing their lines…",
  "约需 10 秒，LLM 正按你写的场景生成 6 段示例对白":
    "About 10 s — the LLM is generating 6 sample exchanges from your scene",
  "重新誊写台词…": "Rewriting the lines…",
  "保持场景不变，重抽一次示例": "Keeping the scene, drawing a fresh set of samples",
  "角色已改动，未保存": "Persona changed, unsaved",
  "保存时会自动重新生成台词": "Saving will regenerate the lines automatically",
  "台词稿尚未生成": "The lines haven't been generated yet",
  "点「重新生成台词」让 TA 有戏可演": "Click “Regenerate lines” to give them something to perform",
  "台词稿已就绪": "The lines are ready",
  "TA 已经准备好出场了": "They're ready to take the stage",
  "尚未塑造角色": "No persona shaped yet",
  "在左侧写下 TA 的样子": "Describe them on the left",
  "翻开角色卡…": "Opening the persona card…",
  "DIRECTOR'S NOTES · 角色卡": "DIRECTOR'S NOTES · Persona",
  "为 TA 写一张角色卡": "Write a persona card for them",
  "这不是给 AI 的指令，是给一名虚拟家教写的剧本。你描述得越具体——TA 是谁、怎么开口、会摆什么神态——":
    "This isn't an instruction to an AI; it's a script for a virtual tutor. The more concretely you describe them — who they are, how they speak, what mannerisms they show — ",
  "TA 表演得就越像真人": "the more human their performance feels",
  "。保存后，系统会基于你的描述自动生成 6 段示范对白，作为 TA 出场前的台词彩排。":
    ". After you save, the system generates 6 sample exchanges from your description as a line rehearsal before they take the stage.",
  "点击替换角色头像": "Click to replace the persona avatar",
  "上传角色头像": "Upload a persona avatar",
  "角色头像": "Persona avatar",
  "一": "I",
  "二": "II",
  "TA 是谁": "Who they are",
  "叙事式描写：名字、身份、和你的关系、性格、说话语气、神态举止。把 TA 当作一个真人，越具体越好。":
    "Write it as a narrative: name, identity, relationship to you, personality, tone of voice, mannerisms. Treat them as a real person — the more concrete, the better.",
  "关于你": "About you",
  "你的背景、学习目标、偏好。TA 会据此调整举例和节奏——比如告诉 TA「我看到公式就头大，请多用图」。":
    "Your background, learning goals, and preferences. They'll adjust examples and pacing accordingly — e.g. tell them “formulas make my head spin, please use more diagrams.”",
  "正在誊写…": "Writing…",
  "保存并生成台词": "Save and generate lines",
  "请先保存场景再重新生成": "Please save the scene before regenerating",
  "用同一场景重新生成示例对白": "Regenerate sample exchanges from the same scene",
  "重写中…": "Rewriting…",
  "↻ 重新生成台词": "↻ Regenerate lines",
  "上次保存 · {at}": "Last saved · {at}",
  "核心教学规则由系统固定，不在此页修改。":
    "The core teaching rules are fixed by the system and aren't changed on this page.",
  "AUDITION · 试镜": "AUDITION",
  "和 TA 演一段": "Rehearse a scene with them",
  "落幕": "Curtain",
  "在左侧写下角色卡，TA 才能上场。":
    "Write the persona card on the left before they can take the stage.",
  "角色刚改过——保存一下，TA 才能就位。":
    "The persona was just changed — save it so they can get into position.",
  "保存后，TA 就准备好上场了。": "Once saved, they're ready to take the stage.",
  "幕布已升，在下方说一句话试试。":
    "The curtain is up — say something below to try it out.",
  "这里聊的不入档，刷新即清空。":
    "Nothing here is recorded; it clears on refresh.",
  "老师在酝酿台词…": "The teacher is composing their lines…",
  "说点什么试试…  (⌘/Ctrl + ↵ 发送)":
    "Say something to try it…  (⌘/Ctrl + ↵ to send)",
  "先保存角色卡": "Save the persona card first",
};
