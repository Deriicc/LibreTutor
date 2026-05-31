import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  CoursesError,
  getChapterTree,
  getCourse,
  isSyntheticKp,
  kpKind,
  syntheticChapterKp,
} from "../api/courses";
import type {
  ChapterTree,
  Course,
  KPStatus,
  KnowledgePointNode,
} from "../api/courses";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; course: Course; tree: ChapterTree }
  | { kind: "error"; status: number; message: string };

const STATUS_LABEL: Record<KPStatus, string> = {
  untouched: "未学",
  in_progress: "学习中",
  passed: "已掌握",
};

const STATUS_BG: Record<KPStatus, string> = {
  untouched: "var(--paper-3)",
  in_progress: "var(--ochre)",
  passed: "var(--sage)",
};

const POLL_INTERVAL_MS = 2000;

/* ---------- ChapterTree sidebar component ---------- */

function StatusGlyph({ status }: { status: KPStatus }) {
  return (
    <span
      className={`dot dot-${status === "in_progress" ? "progress" : status}`}
      title={STATUS_LABEL[status]}
    />
  );
}

function TreeHeader({ tree }: { tree: ChapterTree }) {
  const allKps = tree.chapters
    .flatMap((ch) => ch.sections.flatMap((s) => s.knowledge_points))
    .filter((k) => !isSyntheticKp(k));
  const passed = allKps.filter((k) => k.status === "passed").length;
  const total = allKps.length;
  return (
    <div className="tree-header">
      <div className="tree-header-title serif">章节树</div>
      <div className="tree-header-meta">
        <span className="tnum mono">{passed}</span>
        <span style={{ color: "var(--ink-4)" }}> / {total} KP</span>
        <span className="tree-progress-track">
          <span
            className="tree-progress-fill"
            style={{ width: `${total === 0 ? 0 : (passed / total) * 100}%` }}
          />
        </span>
      </div>
      <div className="tree-legend">
        <span>
          <span className="dot dot-passed" /> 通过
        </span>
        <span>
          <span className="dot dot-progress" /> 学习中
        </span>
        <span>
          <span className="dot dot-untouched" /> 未开始
        </span>
      </div>
    </div>
  );
}

function ChapterTree({
  tree,
  onSelectKp,
}: {
  tree: ChapterTree;
  onSelectKp: (kp: KnowledgePointNode) => void;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    tree.chapters.forEach((ch) => {
      const hasProgress = ch.sections.some((s) =>
        s.knowledge_points.some((k) => k.status !== "untouched"),
      );
      if (hasProgress || ch.status !== "untouched") {
        initial[ch.id] = true;
        ch.sections.forEach((s) => {
          if (s.status !== "untouched") initial[s.id] = true;
        });
      }
    });
    return initial;
  });

  const toggle = (id: string) =>
    setOpen((o) => ({ ...o, [id]: !o[id] }));

  return (
    <div className="tree">
      {tree.chapters.map((ch) => {
        const synthKp = syntheticChapterKp(ch);
        if (synthKp) {
          return (
            <div key={ch.id} className="tree-chapter">
              <div
                className="tree-row tree-row-chapter"
                onClick={() => onSelectKp(synthKp)}
              >
                <span className="twirl" style={{ visibility: "hidden" }}>
                  ▸
                </span>
                <StatusGlyph status={ch.status} />
                <span className="tree-label">{ch.title}</span>
              </div>
            </div>
          );
        }
        return (
          <div key={ch.id} className="tree-chapter">
            <div
              className="tree-row tree-row-chapter"
              onClick={() => toggle(ch.id)}
            >
              <span className={`twirl ${open[ch.id] ? "open" : ""}`}>▸</span>
              <StatusGlyph status={ch.status} />
              <span className="tree-label">{ch.title}</span>
            </div>
            {open[ch.id] &&
            ch.sections.map((s) => (
              <div key={s.id} className="tree-section">
                <div
                  className="tree-row tree-row-section"
                  onClick={() => toggle(s.id)}
                >
                  <span className="indent" />
                  <span className={`twirl ${open[s.id] ? "open" : ""}`}>
                    ▸
                  </span>
                  <StatusGlyph status={s.status} />
                  <span className="tree-label">{s.title}</span>
                </div>
                {open[s.id] &&
                  s.knowledge_points.map((kp) => (
                    <div
                      key={kp.id}
                      className="tree-row tree-row-kp"
                      onClick={() => onSelectKp(kp)}
                    >
                      <span className="indent" />
                      <span className="indent" />
                      {isSyntheticKp(kp) ? (
                        <span
                          className="kp-kind-badge"
                          title="只读：可与老师对话，不计入进度"
                        >
                          {kpKind(kp) === "summary" ? "总结" : "导读"}
                        </span>
                      ) : (
                        <StatusGlyph status={kp.status} />
                      )}
                      <span className="tree-label">{kp.title}</span>
                    </div>
                  ))}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

/* ---------- Generation hero (animated transcription view) ---------- */

type GenStage = "parsing" | "kps" | "binding";

function deriveGenStage(course: Course): GenStage {
  if (course.progress_total === 0) return "parsing";
  if (course.progress_done < course.progress_total) return "kps";
  return "binding";
}

const GEN_STAGES: { key: GenStage; label: string }[] = [
  { key: "parsing", label: "解析目录" },
  { key: "kps", label: "切分知识点" },
  { key: "binding", label: "落定章节" },
];

const STAGE_BLURB: Record<GenStage, { title: string; lines: string[] }> = {
  parsing: {
    title: "解析目录",
    lines: [
      "纸册之上，先识其骨。",
      "系统正在阅读 PDF 文本，由 LLM 推断章节骨架——",
      "目录决定我们的学习路径，约需 1~2 分钟。",
    ],
  },
  kps: {
    title: "切分知识点",
    lines: [
      "目录已知，章节小节皆已就位。",
      "现在为每一节切出 3~7 个聚焦单一概念的知识点，",
      "多节并发处理，互不阻塞——是整个流程里最耗时的一段。",
    ],
  },
  binding: {
    title: "落定章节",
    lines: [
      "知识点已就位。",
      "正在装订成册——稍候片刻即可进入学习。",
    ],
  },
};

function GenerationHero({ course }: { course: Course }) {
  const stage = deriveGenStage(course);
  const activeIdx = GEN_STAGES.findIndex((s) => s.key === stage);
  const pct =
    course.progress_total > 0
      ? Math.min(
          100,
          Math.round((course.progress_done / course.progress_total) * 100),
        )
      : 0;
  const blurb = STAGE_BLURB[stage];

  return (
    <div className="gen-hero">
      <div className="gen-hero-head">
        <svg className="gen-quill" viewBox="0 0 24 24" width="30" height="30">
          <g
            stroke="currentColor"
            strokeWidth="1.5"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M4 20 L13 11" />
            <path d="M13 11 L16 4 L20 8 L13 11 Z" fill="currentColor" />
          </g>
          <circle cx="3.6" cy="20.4" r="0.9" fill="currentColor" />
        </svg>
        <span className="gen-title-text serif">
          正在誊抄章节树
          <span className="gen-dots">
            <span>·</span>
            <span>·</span>
            <span>·</span>
          </span>
        </span>
        {course.progress_total > 0 && (
          <span className="gen-count mono tnum">
            {course.progress_done}
            <span style={{ color: "var(--ink-5)" }}> / </span>
            {course.progress_total} 节
          </span>
        )}
      </div>

      <div className="gen-progress-track">
        <div
          className={`gen-progress-fill ${course.progress_total === 0 ? "gen-progress-indeterminate" : ""}`}
          style={{
            width:
              course.progress_total === 0 ? "30%" : `${Math.max(2, pct)}%`,
          }}
        />
      </div>

      <div className="gen-stages">
        {GEN_STAGES.map((s, i) => (
          <div
            key={s.key}
            className={`gen-stage ${
              i < activeIdx
                ? "gen-stage-done"
                : i === activeIdx
                  ? "gen-stage-active"
                  : "gen-stage-pending"
            }`}
          >
            {i < GEN_STAGES.length - 1 && <div className="gen-stage-line" />}
            <div className="gen-stage-dot" />
            <div className="gen-stage-label">{s.label}</div>
          </div>
        ))}
      </div>

      <div key={stage} className="gen-blurb">
        <div className="gen-blurb-label margin-note">本阶段</div>
        <div className="gen-blurb-title serif">{blurb.title}</div>
        <div className="gen-blurb-body">
          {blurb.lines.map((line, i) => (
            <div
              key={i}
              className="gen-blurb-line"
              style={{ animationDelay: `${i * 90}ms` }}
            >
              {line}
            </div>
          ))}
        </div>
      </div>

      <div className="margin-note gen-footnote">
        每 {POLL_INTERVAL_MS / 1000} 秒自动刷新 · 全程约 5~8 分钟 · 可离开页面
      </div>
    </div>
  );
}

/* ---------- CoursePage ---------- */

function findContinueKp(
  tree: ChapterTree,
): { chapter: string; section: string; kp: KnowledgePointNode } | null {
  for (const ch of tree.chapters) {
    for (const sec of ch.sections) {
      for (const kp of sec.knowledge_points) {
        if (!isSyntheticKp(kp) && kp.status === "in_progress") {
          return { chapter: ch.title, section: sec.title, kp };
        }
      }
    }
  }
  for (const ch of tree.chapters) {
    for (const sec of ch.sections) {
      for (const kp of sec.knowledge_points) {
        if (!isSyntheticKp(kp) && kp.status === "untouched") {
          return { chapter: ch.title, section: sec.title, kp };
        }
      }
    }
  }
  return null;
}

export function CoursePage() {
  const { courseId } = useParams<{ courseId: string }>();
  const navigate = useNavigate();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    if (!courseId) return;
    let cancelled = false;

    async function loadOnce() {
      try {
        const [course, tree] = await Promise.all([
          getCourse(courseId!),
          getChapterTree(courseId!),
        ]);
        if (cancelled) return;
        setState({ kind: "ready", course, tree });

        if (
          course.generation_status === "pending" ||
          course.generation_status === "running"
        ) {
          pollRef.current = window.setTimeout(loadOnce, POLL_INTERVAL_MS);
        }
      } catch (err: unknown) {
        if (cancelled) return;
        if (err instanceof CoursesError) {
          setState({ kind: "error", status: err.status, message: err.message });
        } else {
          setState({ kind: "error", status: 0, message: "加载失败" });
        }
      }
    }

    void loadOnce();
    return () => {
      cancelled = true;
      if (pollRef.current !== null) {
        window.clearTimeout(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [courseId]);

  const continueTarget = useMemo(() => {
    if (state.kind !== "ready") return null;
    return findContinueKp(state.tree);
  }, [state]);

  return (
    <div className="page-in course-page">
      {state.kind === "loading" && (
        <div
          className="margin-note"
          style={{ textAlign: "center", padding: "60px 0 40px" }}
        >
          加载中…
        </div>
      )}

      {state.kind === "error" && (
        <div style={{ padding: 48, textAlign: "center", color: "var(--accent)" }}>
          {state.status === 404 ? "Course 不存在或无权访问" : state.message}
        </div>
      )}

      {state.kind === "ready" && (
        <>
          {/* Left sidebar */}
          <aside className="tree-sidebar">
            <TreeHeader tree={state.tree} />
            <div className="tree-scroll">
              {(state.course.generation_status === "pending" ||
                state.course.generation_status === "running") &&
              state.tree.chapters.length === 0 ? (
                <div className="tree-skel">
                  {[80, 65, 90, 55, 75, 60].map((w, i) => (
                    <div
                      key={i}
                      className="skel tree-skel-row"
                      style={{ width: `${w}%`, animationDelay: `${i * 80}ms` }}
                    />
                  ))}
                  <div
                    className="margin-note"
                    style={{ marginTop: 18, textAlign: "center" }}
                  >
                    章节骨架尚未落定…
                  </div>
                </div>
              ) : (
                <ChapterTree
                  tree={state.tree}
                  onSelectKp={(kp) =>
                    navigate(`/courses/${state.course.id}/kp/${kp.id}`)
                  }
                />
              )}
            </div>
          </aside>

          {/* Main content */}
          <main className="course-main">
            <div className="margin-note">
              {state.course.generation_status === "done"
                ? "课程已就绪"
                : state.course.generation_status === "running"
                  ? "正在生成章节树…"
                  : state.course.generation_status === "failed"
                    ? "生成失败"
                    : "等待生成"}
            </div>
            <h1 style={{ margin: "4px 0 8px" }}>{state.course.name}</h1>
            <div
              style={{
                display: "flex",
                gap: 12,
                marginBottom: 28,
                alignItems: "center",
              }}
            >
              <span className="pill">
                {new Date(state.course.created_at).toLocaleDateString()}
              </span>
              <span className="pill">
                {state.tree.chapters.reduce(
                  (sum, ch) =>
                    sum +
                    ch.sections.reduce(
                      (s, sec) => s + sec.knowledge_points.length,
                      0,
                    ),
                  0,
                )}{" "}
                个 KP
              </span>
              <span
                className={`pill ${state.course.generation_status === "done" ? "pill-sage" : state.course.generation_status === "failed" ? "pill-accent" : "pill-ochre"}`}
              >
                {state.course.generation_status === "done"
                  ? "已完成"
                  : state.course.generation_status === "running"
                    ? "生成中"
                    : state.course.generation_status === "failed"
                      ? "失败"
                      : "等待中"}
              </span>
            </div>

            {/* Generation progress — animated hero */}
            {(state.course.generation_status === "pending" ||
              state.course.generation_status === "running") && (
              <GenerationHero course={state.course} />
            )}

            {state.course.generation_status === "failed" && (
              <div
                className="card"
                style={{
                  padding: 24,
                  marginBottom: 28,
                  borderColor: "var(--accent-tint)",
                  background: "var(--accent-wash)",
                }}
              >
                <div className="serif" style={{ fontSize: 18, marginBottom: 8 }}>
                  章节树生成失败
                </div>
                <div style={{ color: "var(--ink-2)", fontSize: 14 }}>
                  {state.course.generation_error ?? "未知错误"}
                </div>
              </div>
            )}

            {/* Continue learning card */}
            {state.course.generation_status === "done" && continueTarget && (
              <div className="continue-card">
                <div className="continue-label">继续从这里学</div>
                <div className="continue-title serif">
                  {continueTarget.kp.title}
                </div>
                <div className="continue-crumb mono">
                  {continueTarget.chapter}{" "}
                  <span style={{ color: "var(--ink-5)" }}>›</span>{" "}
                  {continueTarget.section}
                </div>
                <div style={{ display: "flex", gap: 12, marginTop: 16 }}>
                  <button
                    className="btn btn-accent btn-lg"
                    onClick={() =>
                      navigate(
                        `/courses/${state.course.id}/kp/${continueTarget.kp.id}`,
                      )
                    }
                  >
                    继续对话 →
                  </button>
                  <button
                    className="btn btn-ghost"
                    onClick={() =>
                      navigate(
                        `/courses/${state.course.id}/kp/${continueTarget.kp.id}/exercise`,
                      )
                    }
                  >
                    跳到作业
                  </button>
                </div>
              </div>
            )}

            {/* Chapter overview */}
            {state.course.generation_status === "done" && (
              <>
                <h3 style={{ margin: "36px 0 8px" }}>章节进度概览</h3>
                <div className="ch-overview">
                  {state.tree.chapters.map((ch) => {
                    const kps = ch.sections.flatMap((s) => s.knowledge_points);
                    const passed = kps.filter((k) => k.status === "passed")
                      .length;
                    const inprog = kps.filter(
                      (k) => k.status === "in_progress",
                    ).length;
                    return (
                      <div key={ch.id} className="ch-row">
                        <div className="ch-status">
                          <span
                            className={`dot dot-${ch.status === "in_progress" ? "progress" : ch.status}`}
                          />
                        </div>
                        <div className="ch-name serif">{ch.title}</div>
                        <div className="ch-bar">
                          {kps.map((k, i) => (
                            <span
                              key={i}
                              className="ch-bar-cell"
                              style={{
                                background: STATUS_BG[k.status],
                              }}
                              title={`${k.title} (${STATUS_LABEL[k.status]})`}
                            />
                          ))}
                        </div>
                        <div className="ch-counts mono tnum">
                          <span style={{ color: "var(--sage)" }}>{passed}</span>
                          <span style={{ color: "var(--ink-5)" }}> · </span>
                          <span style={{ color: "var(--ochre)" }}>
                            {inprog}
                          </span>
                          <span style={{ color: "var(--ink-5)" }}>
                            {" "}
                            / {kps.length}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </main>
        </>
      )}
    </div>
  );
}
