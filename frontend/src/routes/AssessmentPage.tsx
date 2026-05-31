import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { runAssessment, AssessmentError } from "../api/assessment";
import type { Assessment } from "../api/assessment";

const COVERAGE_WARN_THRESHOLD = 0.6;

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; assessment: Assessment }
  | { kind: "error"; message: string };

function CoverageRing({ ratio }: { ratio: number }) {
  // Ratio in [0, 1]. Renders a 240×140 half-donut + percentage center text.
  const pct = Math.max(0, Math.min(1, ratio));
  const dash = pct * 151; // arc length is ~151 for r=48 half-circle
  const danger = pct < COVERAGE_WARN_THRESHOLD;
  return (
    <div className="assessment-ring">
      <svg viewBox="0 0 120 70" width="220" height="130">
        <path
          d="M 12 60 A 48 48 0 0 1 108 60"
          fill="none"
          stroke="var(--paper-3)"
          strokeWidth="8"
          strokeLinecap="round"
        />
        <path
          d="M 12 60 A 48 48 0 0 1 108 60"
          fill="none"
          stroke={danger ? "var(--accent)" : "#557a4b"}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={`${dash} 200`}
        />
        <text
          x="60"
          y="52"
          textAnchor="middle"
          fontFamily="Newsreader, serif"
          fontSize="26"
          fill="var(--ink-0)"
        >
          {Math.round(pct * 100)}%
        </text>
        <text
          x="60"
          y="65"
          textAnchor="middle"
          fontFamily="JetBrains Mono, monospace"
          fontSize="9"
          fill="var(--ink-4)"
        >
          覆盖度
        </text>
      </svg>
    </div>
  );
}

function ConceptList({
  title,
  glyph,
  toneClass,
  items,
}: {
  title: string;
  glyph: string;
  toneClass: string;
  items: { concept: string; detail: string }[];
}) {
  return (
    <div className={`assessment-bucket ${toneClass}`}>
      <div className="assessment-bucket-head">
        <span className="assessment-bucket-glyph">{glyph}</span>
        <span className="assessment-bucket-title">{title}</span>
        <span className="assessment-bucket-count mono">{items.length}</span>
      </div>
      {items.length === 0 ? (
        <div className="assessment-bucket-empty margin-note">（无）</div>
      ) : (
        <ul className="assessment-bucket-list">
          {items.map((it) => (
            <li key={it.concept}>
              <div className="assessment-concept-name">{it.concept}</div>
              <div className="assessment-concept-detail margin-note">
                {it.detail}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function AssessmentPage() {
  const { courseId, kpId } = useParams<{
    courseId: string;
    kpId: string;
  }>();
  const navigate = useNavigate();
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    if (!courseId || !kpId) return;
    let cancelled = false;
    setState({ kind: "loading" });
    runAssessment(courseId, kpId)
      .then((a) => {
        if (cancelled) return;
        setState({ kind: "ready", assessment: a });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg =
          err instanceof AssessmentError ? err.message : "评估失败";
        setState({ kind: "error", message: msg });
      });
    return () => {
      cancelled = true;
    };
  }, [courseId, kpId]);

  function handleStart() {
    if (state.kind !== "ready" || !courseId || !kpId) return;
    navigate(`/courses/${courseId}/kp/${kpId}/exercise`);
  }

  function handleStartWithConfirm() {
    if (state.kind !== "ready") return;
    const ratio = state.assessment.coverage_ratio;
    if (ratio < COVERAGE_WARN_THRESHOLD) {
      const ok = window.confirm(
        `对话覆盖度只有 ${Math.round(ratio * 100)}%，作业题量已自动减少。` +
          `\n\n确认要直接进入作业吗？也可以选择"返回继续学习"`,
      );
      if (!ok) return;
    }
    handleStart();
  }

  return (
    <div className="assessment-page page-in">
      <div className="assessment-shell">
        <header className="assessment-head">
          <div className="margin-note" style={{ fontSize: 11, letterSpacing: "0.1em" }}>
            学习评估
          </div>
          <h1 style={{ margin: "4px 0 0", fontFamily: "Newsreader, serif" }}>
            老师对你的掌握情况怎么看
          </h1>
        </header>

        {state.kind === "loading" && (
          <div className="card assessment-card">
            <div className="assessment-loading">
              <div className="thinking-dots">
                <span />
                <span />
                <span />
              </div>
              <div className="margin-note" style={{ marginTop: 12 }}>
                正在翻看你和老师的对话…
              </div>
            </div>
          </div>
        )}

        {state.kind === "error" && (
          <div className="card assessment-card">
            <div className="assessment-error">
              <div style={{ color: "var(--accent)", fontWeight: 500 }}>
                评估失败
              </div>
              <div className="margin-note" style={{ marginTop: 6 }}>
                {state.message}
              </div>
              <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() =>
                    navigate(`/courses/${courseId}/kp/${kpId}`)
                  }
                >
                  ← 返回对话
                </button>
                <button
                  type="button"
                  className="btn btn-accent btn-sm"
                  onClick={() => {
                    if (!courseId || !kpId) return;
                    setState({ kind: "loading" });
                    runAssessment(courseId, kpId)
                      .then((a) =>
                        setState({ kind: "ready", assessment: a }),
                      )
                      .catch((err: unknown) => {
                        const msg =
                          err instanceof AssessmentError
                            ? err.message
                            : "评估失败";
                        setState({ kind: "error", message: msg });
                      });
                  }}
                >
                  重试
                </button>
              </div>
            </div>
          </div>
        )}

        {state.kind === "ready" && (
          <>
            <div className="card assessment-card">
              <div className="assessment-summary">
                <CoverageRing ratio={state.assessment.coverage_ratio} />
                <div className="assessment-summary-text">
                  <div className="margin-note" style={{ fontSize: 11 }}>
                    老师的判断
                  </div>
                  <div
                    className="serif"
                    style={{
                      fontSize: 16,
                      color: "var(--ink-0)",
                      marginTop: 4,
                      lineHeight: 1.6,
                    }}
                  >
                    {state.assessment.mastery_summary}
                  </div>
                </div>
              </div>

              {state.assessment.coverage_ratio < COVERAGE_WARN_THRESHOLD && (
                <div className="assessment-warning">
                  <strong>覆盖不足</strong>
                  ：建议先回到对话，重点聊一下「未触及」清单里的概念，再来做作业。
                </div>
              )}
            </div>

            <div className="assessment-buckets">
              <ConceptList
                title="已掌握"
                glyph="✓"
                toneClass="bucket-covered"
                items={state.assessment.covered.map((c) => ({
                  concept: c.concept,
                  detail: c.evidence,
                }))}
              />
              <ConceptList
                title="部分掌握"
                glyph="~"
                toneClass="bucket-partial"
                items={state.assessment.partial.map((p) => ({
                  concept: p.concept,
                  detail: p.evidence,
                }))}
              />
              <ConceptList
                title="未触及"
                glyph="—"
                toneClass="bucket-untouched"
                items={state.assessment.untouched.map((u) => ({
                  concept: u.concept,
                  detail: u.reason,
                }))}
              />
            </div>

            <div className="card assessment-card">
              <div
                className="margin-note"
                style={{ fontSize: 12, lineHeight: 1.6 }}
              >
                老师将按本次掌握情况自动出 {state.assessment.suggested_count} 道题
                ·
                {" "}
                {state.assessment.suggested_difficulty === "easy"
                  ? "简单档"
                  : state.assessment.suggested_difficulty === "hard"
                    ? "困难档"
                    : "正常档"}
              </div>
            </div>

            <div className="assessment-actions">
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() =>
                  navigate(`/courses/${courseId}/kp/${kpId}`)
                }
              >
                ← 返回继续学习
              </button>
              <button
                type="button"
                className="btn btn-accent btn-lg"
                onClick={handleStartWithConfirm}
              >
                开始作业 →
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
