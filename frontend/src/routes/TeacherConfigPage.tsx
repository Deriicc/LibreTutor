import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { MarkdownView } from "../components/RichTextEditor";
import {
  TeacherConfigError,
  getTeacherConfig,
  putTeacherConfig,
  regenerateFewShots,
  streamTestChat,
  teacherAvatarUrl,
  uploadTeacherAvatar,
} from "../api/teacher";
import type { TeacherConfig, TestChatMessage } from "../api/teacher";
import { useLanguage } from "../i18n/LanguageContext";
import { et } from "../i18n/translations";

const EMPTY_CONFIG: TeacherConfig = {
  scene: "",
  learner_context: "",
  has_generated_few_shots: false,
  scene_dirty: false,
  has_avatar: false,
};

const SCENE_PLACEHOLDER = `比如：
你是理查德·费曼，加州理工的物理学教授。你最擅长把复杂概念拆成最朴素的大白话，喜欢用第一性原理和生活化的例子来讲解，绝不堆砌术语。你风趣、直率、充满好奇心，常常反问学习者"那你觉得为什么会这样？"来引导他自己想明白。`;

const CONTEXT_PLACEHOLDER = `比如：
大二物理系学生，对量子力学零基础，5 月底前要掌握薛定谔方程的物理图像。我喜欢用类比和具体例子来理解抽象概念。`;

type TestMsg = {
  key: string;
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
};

type StatusKind = "saving" | "regenerating" | "dirty" | "stale" | "ready" | "empty";

function getStatus(args: {
  saving: boolean;
  regenerating: boolean;
  sceneChanged: boolean;
  sceneDirty: boolean;
  hasFewShots: boolean;
}): { kind: StatusKind; label: string; hint: string } {
  if (args.saving) {
    return {
      kind: "saving",
      label: et("正在为 TA 写台词…"),
      hint: et("约需 10 秒，LLM 正按你写的场景生成 6 段示例对白"),
    };
  }
  if (args.regenerating) {
    return {
      kind: "regenerating",
      label: et("重新誊写台词…"),
      hint: et("保持场景不变，重抽一次示例"),
    };
  }
  if (args.sceneChanged) {
    return {
      kind: "dirty",
      label: et("角色已改动，未保存"),
      hint: et("保存时会自动重新生成台词"),
    };
  }
  if (args.sceneDirty) {
    return {
      kind: "stale",
      label: et("台词稿尚未生成"),
      hint: et("点「重新生成台词」让 TA 有戏可演"),
    };
  }
  if (args.hasFewShots) {
    return {
      kind: "ready",
      label: et("台词稿已就绪"),
      hint: et("TA 已经准备好出场了"),
    };
  }
  return { kind: "empty", label: et("尚未塑造角色"), hint: et("在左侧写下 TA 的样子") };
}

export function TeacherConfigPage() {
  const { t } = useLanguage();
  const { courseId } = useParams<{ courseId: string }>();
  const scenePlaceholder = t(SCENE_PLACEHOLDER);
  const contextPlaceholder = t(CONTEXT_PLACEHOLDER);
  const [config, setConfig] = useState<TeacherConfig>(EMPTY_CONFIG);
  const [origScene, setOrigScene] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  // Bumped after a successful upload to bust the <img> cache so the
  // freshly replaced avatar shows without a manual reload.
  const [avatarVersion, setAvatarVersion] = useState(0);

  const [testMessages, setTestMessages] = useState<TestMsg[]>([]);
  const [testInput, setTestInput] = useState("");
  const [testSending, setTestSending] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  // Streaming text lives outside `testMessages` so deltas don't force the
  // whole list (and its expensive Markdown bubbles) to re-render.
  const [streamingKey, setStreamingKey] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState("");
  const streamingBufRef = useRef("");
  const rafRef = useRef<number | null>(null);
  const testStreamRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!courseId) return;
    let cancelled = false;
    getTeacherConfig(courseId)
      .then((c) => {
        if (cancelled) return;
        setConfig(c);
        setOrigScene(c.scene);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const m = err instanceof TeacherConfigError ? err.message : t("加载失败");
        setError(m);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  // Cancel any pending rAF when the component unmounts.
  useEffect(() => {
    return () => {
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, []);

  // Auto-scroll to bottom — but only if user is already near bottom, so we
  // don't yank them away when they've scrolled up to read.
  useEffect(() => {
    const el = testStreamRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distance < 240) {
      el.scrollTop = el.scrollHeight;
    }
  }, [testMessages, streamingText]);

  const sceneChanged = config.scene !== origScene;
  const canTest =
    !!config.scene.trim() && !sceneChanged && !saving && !regenerating;
  const status = getStatus({
    saving,
    regenerating,
    sceneChanged,
    sceneDirty: config.scene_dirty,
    hasFewShots: config.has_generated_few_shots,
  });

  function update<K extends keyof TeacherConfig>(field: K, value: TeacherConfig[K]) {
    setConfig((c) => ({ ...c, [field]: value }));
  }

  async function handleSave() {
    if (!courseId || saving) return;
    setSaving(true);
    setError(null);
    try {
      const out = await putTeacherConfig(courseId, {
        scene: config.scene,
        learner_context: config.learner_context,
      });
      setConfig(out);
      setOrigScene(out.scene);
      setSavedAt(new Date().toLocaleTimeString());
    } catch (err: unknown) {
      const m = err instanceof TeacherConfigError ? err.message : t("保存失败");
      setError(m);
    } finally {
      setSaving(false);
    }
  }

  async function handleAvatarPick(file: File | null) {
    if (!courseId || !file || uploadingAvatar) return;
    setUploadingAvatar(true);
    setError(null);
    try {
      const out = await uploadTeacherAvatar(courseId, file);
      setConfig(out);
      setAvatarVersion(Date.now());
    } catch (err: unknown) {
      const m = err instanceof TeacherConfigError ? err.message : t("头像上传失败");
      setError(m);
    } finally {
      setUploadingAvatar(false);
    }
  }

  async function handleRegenerate() {
    if (!courseId || regenerating) return;
    setRegenerating(true);
    setError(null);
    try {
      const out = await regenerateFewShots(courseId);
      setConfig(out);
      setOrigScene(out.scene);
      setSavedAt(new Date().toLocaleTimeString());
    } catch (err: unknown) {
      const m = err instanceof TeacherConfigError ? err.message : t("重新生成失败");
      setError(m);
    } finally {
      setRegenerating(false);
    }
  }

  async function handleTestSend() {
    if (!courseId || testSending || !testInput.trim()) return;
    const userText = testInput.trim();
    const userKey = `u-${Date.now()}`;
    const aiKey = `a-${Date.now() + 1}`;
    setTestMessages((m) => [
      ...m,
      { key: userKey, role: "user", content: userText },
      { key: aiKey, role: "assistant", content: "", pending: true },
    ]);
    setTestInput("");
    setTestSending(true);
    setTestError(null);
    streamingBufRef.current = "";
    setStreamingKey(aiKey);
    setStreamingText("");

    const apiMessages: TestChatMessage[] = testMessages
      .filter((m) => !m.pending)
      .map((m) => ({ role: m.role, content: m.content }));
    apiMessages.push({ role: "user", content: userText });

    const cancelRaf = () => {
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };

    await streamTestChat(courseId, apiMessages, {
      onDelta: (delta) => {
        // Buffer in a ref; coalesce setState to one update per animation frame
        // so we don't re-parse Markdown on every chunk.
        streamingBufRef.current += delta;
        if (rafRef.current == null) {
          rafRef.current = requestAnimationFrame(() => {
            rafRef.current = null;
            setStreamingText(streamingBufRef.current);
          });
        }
      },
      onDone: () => {
        cancelRaf();
        const finalText = streamingBufRef.current;
        streamingBufRef.current = "";
        // Commit the streamed text into the message list, *then* clear the
        // streaming state. Order matters: the AI bubble switches from plain
        // text (streamingText) to MarkdownView (m.content) in one paint.
        setTestMessages((arr) =>
          arr.map((m) =>
            m.key === aiKey
              ? { ...m, content: finalText, pending: false }
              : m,
          ),
        );
        setStreamingKey(null);
        setStreamingText("");
        setTestSending(false);
      },
      onError: (message) => {
        cancelRaf();
        streamingBufRef.current = "";
        setTestError(message);
        setTestMessages((arr) => arr.filter((m) => m.key !== aiKey));
        setStreamingKey(null);
        setStreamingText("");
        setTestSending(false);
      },
    });
  }

  function resetTest() {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    streamingBufRef.current = "";
    setStreamingKey(null);
    setStreamingText("");
    setTestMessages([]);
    setTestError(null);
  }

  function handleTestKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      void handleTestSend();
    }
  }

  return (
    <main className="casting-page page-in">
      {/* Loading curtain — match the diary "翻开日记本…" entrance:
          only a single small line, no header, no ornaments. */}
      {loading && (
        <div
          className="margin-note"
          style={{ textAlign: "center", padding: "60px 0 40px" }}
        >
          {t("翻开角色卡…")}
        </div>
      )}

      {!loading && (
        <>
          {/* Page header ============================================ */}
          <div className="casting-back-wrap">
            <Link
              to={courseId ? `/courses/${courseId}` : "/"}
              className="btn btn-quiet btn-sm upload-back-link"
            >
              {t("← 返回章节树")}
            </Link>
          </div>
          <header className="casting-head">
            <div className="casting-titleblock">
              <div className="margin-note casting-eyebrow">
                {t("DIRECTOR'S NOTES · 角色卡")}
              </div>
              <h1 className="casting-title">{t("为 TA 写一张角色卡")}</h1>
              <p className="casting-lede">
                {t("这不是给 AI 的指令，是给一名虚拟家教写的剧本。你描述得越具体——TA 是谁、怎么开口、会摆什么神态——")}
                <em>{t("TA 表演得就越像真人")}</em>
                {t("。保存后，系统会基于你的描述自动生成 6 段示范对白，作为 TA 出场前的台词彩排。")}
              </p>
            </div>
            <label
              className={`casting-portrait${
                config.has_avatar ? " is-filled" : ""
              }${uploadingAvatar ? " is-uploading" : ""}`}
              title={config.has_avatar ? t("点击替换角色头像") : t("上传角色头像")}
            >
              {config.has_avatar && courseId && (
                <img
                  className="casting-portrait-img"
                  src={teacherAvatarUrl(courseId, avatarVersion)}
                  alt={t("角色头像")}
                />
              )}
              <span className="casting-portrait-plus" aria-hidden="true">
                {uploadingAvatar ? "…" : "+"}
              </span>
              <input
                type="file"
                accept="image/*"
                onChange={(e) =>
                  void handleAvatarPick(e.target.files?.[0] ?? null)
                }
                disabled={uploadingAvatar}
                style={{ display: "none" }}
              />
            </label>
            <div className="casting-ornament" aria-hidden="true">
              ❦
            </div>
          </header>

          <div className="book-rule" />

          <div className="casting-grid">
          {/* LEFT — script form ============================== */}
          <section className="casting-form">
            <article className="casting-section">
              <header className="casting-section-head">
                <div className="casting-section-num">{t("一")}</div>
                <div>
                  <h2 className="casting-section-title">
                    {t("TA 是谁")}
                  </h2>
                  <div className="margin-note casting-section-sub">
                    {t("叙事式描写：名字、身份、和你的关系、性格、说话语气、神态举止。把 TA 当作一个真人，越具体越好。")}
                  </div>
                </div>
              </header>
              <textarea
                id="scene"
                className="manuscript-input"
                value={config.scene}
                onChange={(e) => update("scene", e.target.value)}
                placeholder={scenePlaceholder}
                rows={14}
                disabled={saving || regenerating}
              />
            </article>

            <div className="casting-divider" aria-hidden="true">
              <span>✦</span>
            </div>

            <article className="casting-section">
              <header className="casting-section-head">
                <div className="casting-section-num">{t("二")}</div>
                <div>
                  <h2 className="casting-section-title">{t("关于你")}</h2>
                  <div className="margin-note casting-section-sub">
                    {t("你的背景、学习目标、偏好。TA 会据此调整举例和节奏——比如告诉 TA「我看到公式就头大，请多用图」。")}
                  </div>
                </div>
              </header>
              <textarea
                id="learner_context"
                className="manuscript-input manuscript-input-sm"
                value={config.learner_context}
                onChange={(e) => update("learner_context", e.target.value)}
                placeholder={contextPlaceholder}
                rows={6}
                disabled={saving || regenerating}
              />
            </article>

            {/* Status + Actions ===================== */}
            <div className={`casting-status casting-status-${status.kind}`}>
              <span className="casting-status-dot" aria-hidden="true" />
              <div className="casting-status-text">
                <div className="casting-status-label">{status.label}</div>
                <div className="margin-note casting-status-hint">
                  {status.hint}
                </div>
              </div>
              {(saving || regenerating) && (
                <span className="thinking-dots casting-status-dots">
                  <span />
                  <span />
                  <span />
                </span>
              )}
            </div>

            <div className="casting-actions">
              <button
                type="button"
                className="btn btn-accent btn-lg"
                disabled={saving || regenerating}
                onClick={() => void handleSave()}
              >
                {saving ? t("正在誊写…") : t("保存并生成台词")}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={
                  saving || regenerating || sceneChanged || !config.scene.trim()
                }
                onClick={() => void handleRegenerate()}
                title={
                  sceneChanged
                    ? t("请先保存场景再重新生成")
                    : t("用同一场景重新生成示例对白")
                }
              >
                {regenerating ? t("重写中…") : t("↻ 重新生成台词")}
              </button>
              <div className="casting-actions-meta">
                {error && (
                  <span style={{ color: "var(--accent)" }}>{error}</span>
                )}
                {savedAt && !error && !saving && !regenerating && (
                  <span style={{ color: "var(--sage)" }}>
                    {t("上次保存 · {at}", { at: savedAt })}
                  </span>
                )}
              </div>
            </div>

            <p className="casting-footnote margin-note">
              {t("核心教学规则由系统固定，不在此页修改。")}
            </p>
          </section>

          {/* RIGHT — audition stage ========================== */}
          <aside className="audition">
            <header className="audition-head">
              <div>
                <div className="margin-note audition-eyebrow">
                  {t("AUDITION · 试镜")}
                </div>
                <h3 className="audition-title">{t("和 TA 演一段")}</h3>
              </div>
              {testMessages.length > 0 && (
                <button
                  type="button"
                  className="btn btn-quiet btn-sm"
                  onClick={resetTest}
                  disabled={testSending}
                >
                  {t("落幕")}
                </button>
              )}
            </header>

            <div className="audition-curtain" aria-hidden="true" />

            <div className="audition-stage" ref={testStreamRef}>
              {!canTest && testMessages.length === 0 && (
                <div className="audition-empty">
                  <div className="audition-empty-glyph">❧</div>
                  <div className="audition-empty-text serif">
                    {!config.scene.trim()
                      ? t("在左侧写下角色卡，TA 才能上场。")
                      : sceneChanged
                        ? t("角色刚改过——保存一下，TA 才能就位。")
                        : t("保存后，TA 就准备好上场了。")}
                  </div>
                </div>
              )}
              {canTest && testMessages.length === 0 && (
                <div className="audition-empty">
                  <div className="audition-empty-glyph">❧</div>
                  <div className="audition-empty-text serif">
                    {t("幕布已升，在下方说一句话试试。")}
                  </div>
                  <div className="margin-note audition-empty-hint">
                    {t("这里聊的不入档，刷新即清空。")}
                  </div>
                </div>
              )}
              {testMessages.map((m) =>
                m.role === "user" ? (
                  <div key={m.key} className="msg msg-user">
                    <div className="msg-bubble msg-bubble-user">{m.content}</div>
                  </div>
                ) : (
                  <div key={m.key} className="msg msg-ai">
                    <div className="msg-ai-mark">
                      <div className="mark">S</div>
                    </div>
                    <div className="msg-ai-body">
                      <div className="msg-bubble msg-bubble-ai">
                        {m.key === streamingKey ? (
                          streamingText ? (
                            <span className="audition-streaming-text">
                              {streamingText}
                            </span>
                          ) : (
                            <span className="msg-pending">
                              <span className="msg-pending-text">
                                {t("老师在酝酿台词…")}
                              </span>
                              <span className="thinking-dots">
                                <span />
                                <span />
                                <span />
                              </span>
                            </span>
                          )
                        ) : m.content ? (
                          <MarkdownView source={m.content} />
                        ) : m.pending ? (
                          <span className="msg-pending">
                            <span className="msg-pending-text">
                              {t("老师在酝酿台词…")}
                            </span>
                            <span className="thinking-dots">
                              <span />
                              <span />
                              <span />
                            </span>
                          </span>
                        ) : null}
                      </div>
                    </div>
                  </div>
                ),
              )}
            </div>

            {testError && (
              <div className="audition-error">{testError}</div>
            )}

            <div className="paper-composer paper-composer-compact">
              <textarea
                className="paper-composer-input"
                value={testInput}
                onChange={(e) => setTestInput(e.target.value)}
                placeholder={
                  canTest ? t("说点什么试试…  (⌘/Ctrl + ↵ 发送)") : t("先保存角色卡")
                }
                onKeyDown={handleTestKeyDown}
                rows={2}
                disabled={!canTest || testSending}
              />
              <button
                type="button"
                className="paper-composer-send"
                aria-label={t("发送")}
                disabled={!canTest || testSending || !testInput.trim()}
                onClick={() => void handleTestSend()}
              >
                <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                  <g
                    stroke="currentColor"
                    strokeWidth="1.6"
                    fill="none"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M4 20 L13 11" />
                    <path d="M13 11 L16 4 L20 8 L13 11 Z" fill="currentColor" />
                  </g>
                  <circle cx="3.6" cy="20.4" r="0.9" fill="currentColor" />
                </svg>
              </button>
            </div>
          </aside>
        </div>
        </>
      )}
    </main>
  );
}
