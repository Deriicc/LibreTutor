import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { MarkdownView, RichTextEditor } from "../components/RichTextEditor";
import {
  KPError,
  advanceKP,
  getSubmission,
  postExerciseSet,
  regradeSubmission,
  submitAnswers,
} from "../api/kp";
import type {
  Exercise,
  KPContent,
  PerQuestionGrade,
  SubmissionResult,
} from "../api/kp";
import { useLanguage } from "../i18n/LanguageContext";

function ExerciseLoadingCard() {
  const { t } = useLanguage();
  const [stage, setStage] = useState(0);
  const stages = [
    { glyph: "📖", text: "翻看课本…" },
    { glyph: "✦", text: "斟酌题目…" },
    { glyph: "✎", text: "誊写题面…" },
  ];

  useEffect(() => {
    const timers: number[] = [];
    timers.push(window.setTimeout(() => setStage(1), 5000));
    timers.push(window.setTimeout(() => setStage(2), 12000));
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, []);

  return (
    <div className="exercise-loading">
      <div className="exercise-loading-card">
        <svg
          className="exercise-loading-quill"
          viewBox="0 0 64 64"
          width="84"
          height="84"
          aria-hidden="true"
        >
          {/* paper stack */}
          <rect
            x="14"
            y="22"
            width="34"
            height="32"
            rx="2"
            fill="var(--paper-2)"
            stroke="var(--ink-4)"
            strokeWidth="1"
          />
          <rect
            x="10"
            y="18"
            width="34"
            height="32"
            rx="2"
            fill="var(--paper-1)"
            stroke="var(--ink-4)"
            strokeWidth="1"
          />
          <line x1="16" y1="28" x2="38" y2="28" stroke="var(--ink-5)" strokeWidth="1" />
          <line x1="16" y1="34" x2="34" y2="34" stroke="var(--ink-5)" strokeWidth="1" />
          <line x1="16" y1="40" x2="36" y2="40" stroke="var(--ink-5)" strokeWidth="1" />
          {/* quill */}
          <g
            stroke="var(--accent)"
            strokeWidth="1.8"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M30 38 L48 20" />
            <path d="M48 20 L56 8 L60 12 L48 20 Z" fill="var(--accent-tint)" />
          </g>
          <circle cx="29.5" cy="38.6" r="1.2" fill="var(--accent)" />
        </svg>
        <div className="exercise-loading-stage">
          <span className="exercise-loading-glyph">{stages[stage].glyph}</span>
          <span className="serif" style={{ fontSize: 17 }}>
            {t(stages[stage].text)}
          </span>
        </div>
        <div className="margin-note" style={{ fontSize: 12 }}>
          {t("首次约 10–20 秒")}
        </div>
        <div className="exercise-loading-bar">
          <div className="exercise-loading-bar-fill" />
        </div>
      </div>
    </div>
  );
}

type State =
  | { kind: "loading" }
  | {
      kind: "answering";
      content: KPContent;
      answers: Record<number, string>;
    }
  | {
      kind: "grading";
      content: KPContent;
      answers: Record<number, string>;
      submissionId: string;
    }
  | {
      kind: "grade_failed";
      content: KPContent;
      answers: Record<number, string>;
      submissionId: string;
      message: string;
    }
  | {
      kind: "graded";
      content: KPContent;
      answers: Record<number, string>;
      result: SubmissionResult;
    }
  | { kind: "error"; message: string };

const POLL_INTERVAL_MS = 2000;

function ShortAnswerQuestion({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="exercise-short">
      <RichTextEditor
        value={value}
        onChange={onChange}
        disabled={disabled}
        rows={4}
      />
    </div>
  );
}

function ExerciseCard({
  index,
  exercise,
  studentAnswer,
  onAnswerChange,
  disabled,
  grade,
  showCorrect,
}: {
  index: number;
  exercise: Exercise;
  studentAnswer: string;
  onAnswerChange: (v: string) => void;
  disabled: boolean;
  grade?: PerQuestionGrade;
  showCorrect?: boolean;
}) {
  const { t } = useLanguage();
  const isMcq = exercise.type === "mcq";
  const correctAnswer = exercise.correct_answer;

  return (
    <article className="exercise-card card">
      <div className="exercise-head">
        <div className="exercise-num mono">
          {String(index + 1).padStart(2, "0")}
        </div>
        <div className="exercise-meta">
          {grade && (
            <span
              className={`pill ${grade.score >= 80 ? "pill-sage" : grade.score >= 60 ? "pill-ochre" : "pill-accent"}`}
            >
              {grade.score >= 80
                ? t("✓ 答对")
                : grade.score >= 60
                  ? t("△ 待加强")
                  : t("✗ 答错")}
              {` · ${grade.score}/100`}
            </span>
          )}
          <span className="pill">
            {exercise.type === "mcq" ? t("选择题") : t("简答题")} ·{" "}
            {exercise.question_type}
          </span>
        </div>
      </div>

      <div className="exercise-q serif">
        <MarkdownView source={exercise.question} />
      </div>

      {isMcq ? (
        <div className="exercise-options">
          {(exercise.options ?? []).map((opt) => {
            const selected = studentAnswer === opt.label;
            const isCorrect = showCorrect && opt.label === correctAnswer;
            const isWrong =
              showCorrect && selected && opt.label !== correctAnswer;
            return (
              <button
                key={opt.label}
                type="button"
                disabled={disabled}
                className={`exercise-option ${selected ? "sel" : ""} ${isCorrect ? "right" : ""} ${isWrong ? "wrong" : ""}`}
                onClick={() => onAnswerChange(opt.label)}
              >
                <span className="opt-letter mono">{opt.label}</span>
                <span>{opt.text}</span>
                {isCorrect && <span className="opt-mark">✓</span>}
                {isWrong && <span className="opt-mark">✗</span>}
              </button>
            );
          })}
        </div>
      ) : (
        <ShortAnswerQuestion
          value={studentAnswer}
          onChange={onAnswerChange}
          disabled={disabled}
        />
      )}

      {grade && (
        <div className="exercise-feedback">
          <div className="exercise-feedback-mark">{t("老师评语")}</div>
          <MarkdownView source={grade.feedback} />
        </div>
      )}

      {showCorrect && isMcq && (
        <div
          style={{
            marginTop: 12,
            padding: "8px 12px",
            background: "var(--sage-wash)",
            borderRadius: "var(--r-2)",
            fontSize: 13,
            color: "var(--sage)",
          }}
        >
          <strong>{t("参考答案：")}</strong>
          {correctAnswer}
        </div>
      )}
    </article>
  );
}

export function ExercisePage() {
  const { t } = useLanguage();
  const { courseId, kpId } = useParams<{
    courseId: string;
    kpId: string;
  }>();
  const navigate = useNavigate();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [advancing, setAdvancing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    if (!courseId || !kpId) return;
    let cancelled = false;

    async function loadContent() {
      try {
        // Drive the LLM tailor synchronously from this page so the
        // ExerciseLoadingCard animation is visible while we wait.
        // postExerciseSet short-circuits when the cached row already
        // matches the assessor's suggestion.
        const content = await postExerciseSet(courseId!, kpId!);
        if (cancelled) return;
        const initialAnswers: Record<number, string> = {};
        content.exercises.forEach((_, i) => {
          initialAnswers[i] = "";
        });
        setState({ kind: "answering", content, answers: initialAnswers });
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof KPError ? err.message : t("加载失败");
        setState({ kind: "error", message });
      }
    }

    void loadContent();
    return () => {
      cancelled = true;
      if (pollRef.current !== null) {
        window.clearTimeout(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [courseId, kpId, reloadKey]);

  function updateAnswer(index: number, value: string) {
    setState((s) =>
      s.kind === "answering"
        ? { ...s, answers: { ...s.answers, [index]: value } }
        : s,
    );
  }

  async function handleSubmit() {
    if (!courseId || !kpId) return;
    if (state.kind !== "answering") return;

    const answersList = state.content.exercises.map((_, i) => ({
      index: i,
      answer: state.answers[i] ?? "",
    }));

    try {
      const meta = await submitAnswers(courseId, kpId, answersList);
      setState({
        kind: "grading",
        content: state.content,
        answers: state.answers,
        submissionId: meta.id,
      });
      schedulePoll(meta.id);
    } catch (err: unknown) {
      const message = err instanceof KPError ? err.message : t("提交失败");
      setState({ kind: "error", message });
    }
  }

  function schedulePoll(submissionId: string) {
    pollRef.current = window.setTimeout(() => {
      void pollOnce(submissionId);
    }, POLL_INTERVAL_MS);
  }

  async function pollOnce(submissionId: string) {
    if (!courseId || !kpId) return;
    try {
      const result = await getSubmission(courseId, kpId, submissionId);
      if (result.submission.status === "done" && result.grade) {
        setState((s) =>
          s.kind === "grading" || s.kind === "graded"
            ? { kind: "graded", content: s.content, answers: s.answers, result }
            : s,
        );
        return;
      }
      if (result.submission.status === "failed") {
        const failMessage = result.submission.error ?? t("评分失败");
        setState((s) =>
          s.kind === "grading"
            ? {
                kind: "grade_failed",
                content: s.content,
                answers: s.answers,
                submissionId: s.submissionId,
                message: failMessage,
              }
            : { kind: "error", message: failMessage },
        );
        return;
      }
      schedulePoll(submissionId);
    } catch (err: unknown) {
      const message = err instanceof KPError ? err.message : t("查询批改状态失败");
      setState({ kind: "error", message });
    }
  }

  async function handleRegrade() {
    if (!courseId || !kpId || state.kind !== "grade_failed") return;
    try {
      await regradeSubmission(courseId, kpId, state.submissionId);
      setState({
        kind: "grading",
        content: state.content,
        answers: state.answers,
        submissionId: state.submissionId,
      });
      schedulePoll(state.submissionId);
    } catch (err: unknown) {
      const message = err instanceof KPError ? err.message : t("重新批改失败");
      setState({ kind: "error", message });
    }
  }

  const hasContent =
    state.kind === "answering" ||
    state.kind === "grading" ||
    state.kind === "grade_failed" ||
    state.kind === "graded";

  const allAnswered = hasContent
    ? state.content.exercises.every((ex, i) => {
        if (ex.type === "mcq") return !!state.answers[i];
        return (state.answers[i] ?? "").trim().length > 0;
      })
    : false;

  const answeredCount = hasContent
    ? state.content.exercises.filter((ex, i) => {
        if (ex.type === "mcq") return !!state.answers[i];
        return (state.answers[i] ?? "").trim().length > 0;
      }).length
    : 0;

  return (
    <main
      className="page-in"
      style={{ maxWidth: 920, margin: "0 auto", padding: "32px 32px 120px", minHeight: "100vh" }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          marginBottom: 8,
        }}
      >
        <button
          type="button"
          className="btn btn-quiet btn-sm"
          onClick={() => navigate(`/courses/${courseId}/kp/${kpId}`)}
        >
          {t("← 回到对话")}
        </button>
      </div>
      <h1 style={{ margin: "4px 0 4px" }}>{t("作业")}</h1>
      <div className="margin-note" style={{ marginBottom: 28 }}>
        {hasContent
          ? (() => {
              const exs = state.content.exercises;
              const mcq = exs.filter((e) => e.type === "mcq").length;
              const short = exs.filter((e) => e.type === "short_answer").length;
              const parts: string[] = [];
              if (mcq) parts.push(t("{n} 道选择", { n: mcq }));
              if (short) parts.push(t("{n} 道简答", { n: short }));
              return t("{total} 道题 · {parts}", { total: exs.length, parts: parts.join(" + ") });
            })()
          : t("加载题目中…")}
      </div>

      {state.kind === "loading" && <ExerciseLoadingCard />}

      {state.kind === "error" && (
        <p style={{ color: "var(--accent)" }}>{state.message}</p>
      )}

      {hasContent && (
        <>
          {/* Grading banner */}
          {state.kind === "grading" && (
            <div className="card grading-card">
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  marginBottom: 10,
                }}
              >
                <span className="upload-spinner big" />
                <div>
                  <div className="serif" style={{ fontSize: 18 }}>
                    {t("AI 老师正在批阅…")}
                  </div>
                  <div className="margin-note">
                    {t("异步进行 · 每 {n} 秒自动刷新", { n: POLL_INTERVAL_MS / 1000 })}
                  </div>
                </div>
              </div>
              <div className="progress-track">
                <div
                  className="progress-fill"
                  style={{
                    width: "60%",
                    animation: "pulse 1.5s ease-in-out infinite",
                  }}
                />
              </div>
              <div className="grading-stages">
                <div className="grading-stage done">{t("① MCQ 比对")}</div>
                <div className="grading-stage active">{t("② 简答 LLM 评分")}</div>
                <div className="grading-stage">{t("③ 综合判定")}</div>
              </div>
            </div>
          )}

          {/* Grade failed banner */}
          {state.kind === "grade_failed" && (
            <div className="card grading-card">
              <div
                className="serif"
                style={{ fontSize: 18, color: "var(--accent)" }}
              >
                {t("批阅失败")}
              </div>
              <div
                className="margin-note"
                style={{ marginTop: 6, marginBottom: 14, maxWidth: 520 }}
              >
                {state.message}
              </div>
              <button
                type="button"
                className="btn btn-accent"
                onClick={() => void handleRegrade()}
              >
                {t("重新批改")}
              </button>
            </div>
          )}

          {/* Grade result banner */}
          {state.kind === "graded" && state.result.grade && (
            <div className="grade-banner card">
              <div className="grade-score">
                <div className="grade-score-num serif tnum">
                  {state.result.grade.overall_score}
                </div>
                <div className="grade-score-of mono">/ 100</div>
              </div>
              <div className="grade-summary">
                <div
                  className="serif"
                  style={{ fontSize: 20, color: "var(--ink-0)" }}
                >
                  {state.result.suggestion ?? t("已提交")}
                </div>
                <div
                  className="margin-note"
                  style={{ maxWidth: 480, marginTop: 4 }}
                >
                  {state.result.grade.overall_feedback}
                </div>
                <div className="grade-actions">
                  <button
                    type="button"
                    className="btn btn-accent"
                    disabled={advancing}
                    onClick={async () => {
                      if (!courseId || !kpId) return;
                      setAdvancing(true);
                      try {
                        await advanceKP(courseId, kpId, "retry");
                        setState({ kind: "loading" });
                        setReloadKey((k) => k + 1);
                      } catch (err: unknown) {
                        const m =
                          err instanceof KPError ? err.message : t("操作失败");
                        setState({ kind: "error", message: m });
                      } finally {
                        setAdvancing(false);
                      }
                    }}
                  >
                    {t("重做一组（生成新题）")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    disabled={advancing}
                    onClick={async () => {
                      if (!courseId || !kpId) return;
                      setAdvancing(true);
                      try {
                        await advanceKP(courseId, kpId, "next");
                        navigate(`/courses/${courseId}`);
                      } catch (err: unknown) {
                        const m =
                          err instanceof KPError ? err.message : t("操作失败");
                        setState({ kind: "error", message: m });
                      } finally {
                        setAdvancing(false);
                      }
                    }}
                  >
                    {t("下一个 KP →")}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Exercise list */}
          <div className="exercise-list">
            {state.content.exercises.map((ex, i) => (
              <ExerciseCard
                key={i}
                index={i}
                exercise={ex}
                studentAnswer={state.answers[i] ?? ""}
                onAnswerChange={(v) => updateAnswer(i, v)}
                disabled={state.kind !== "answering"}
                grade={
                  state.kind === "graded"
                    ? state.result.grade?.per_question.find(
                        (g) => g.index === i,
                      )
                    : undefined
                }
                showCorrect={state.kind === "graded"}
              />
            ))}
          </div>

          {/* Submit bar */}
          {state.kind === "answering" && (
            <div className="exercise-submit-bar">
              <div className="margin-note">
                {t("已作答")}{" "}
                <span className="mono tnum" style={{ color: "var(--ink-1)" }}>
                  {answeredCount}
                </span>{" "}
                / {state.content.exercises.length}
              </div>
              <button
                type="button"
                className="btn btn-accent btn-lg"
                onClick={() => void handleSubmit()}
                disabled={!allAnswered}
              >
                {t("提交作业")}
              </button>
            </div>
          )}
        </>
      )}
    </main>
  );
}
