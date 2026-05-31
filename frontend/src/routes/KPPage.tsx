import { memo, useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  CoursesError,
  getChapterTree,
  isSyntheticKp,
  kpKind,
  syntheticChapterKp,
} from "../api/courses";
import type {
  ChapterTree,
  KnowledgePointNode,
} from "../api/courses";
import {
  ChatError,
  listMessages,
  openDialogueStream,
  sendMessageStream,
} from "../api/chat";
import type { ChatMessage, MessageRole, StreamHandlers } from "../api/chat";
import { getKPContent } from "../api/kp";
import { getTeacherConfig, teacherAvatarUrl } from "../api/teacher";
import { MarkdownView } from "../components/RichTextEditor";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; tree: ChapterTree; kp: KnowledgePointNode }
  | { kind: "not-found" }
  | { kind: "error"; message: string };

type ChatBubble = {
  key: string;
  role: MessageRole;
  content: string;
  pending?: boolean;
};

function toBubble(m: ChatMessage): ChatBubble {
  return { key: m.id, role: m.role, content: m.content };
}

function findKpInTree(
  tree: ChapterTree,
  kpId: string,
): { chapter: string; section: string; kp: KnowledgePointNode } | null {
  for (const ch of tree.chapters) {
    for (const sec of ch.sections) {
      for (const kp of sec.knowledge_points) {
        if (kp.id === kpId) {
          return { chapter: ch.title, section: sec.title, kp };
        }
      }
    }
  }
  return null;
}

/* ---------- Mini tree for sidebar ---------- */

function StatusGlyph({ status }: { status: string }) {
  return (
    <span
      className={`dot dot-${status === "in_progress" ? "progress" : status}`}
    />
  );
}

const MiniChapterTree = memo(function MiniChapterTree({
  tree,
  currentKpId,
  onSelectKp,
}: {
  tree: ChapterTree;
  currentKpId: string;
  onSelectKp: (kpId: string) => void;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    tree.chapters.forEach((ch) => {
      const hasCurrent = ch.sections.some((s) =>
        s.knowledge_points.some((k) => k.id === currentKpId),
      );
      if (hasCurrent) {
        initial[ch.id] = true;
        ch.sections.forEach((s) => {
          if (s.knowledge_points.some((k) => k.id === currentKpId))
            initial[s.id] = true;
        });
      }
    });
    return initial;
  });

  const toggle = (id: string) =>
    setOpen((o) => ({ ...o, [id]: !o[id] }));

  return (
    <div className="tree tree-dense">
      {tree.chapters.map((ch) => {
        const synthKp = syntheticChapterKp(ch);
        if (synthKp) {
          const isCurrent = synthKp.id === currentKpId;
          return (
            <div key={ch.id} className="tree-chapter">
              <div
                className={`tree-row tree-row-chapter ${isCurrent ? "is-current" : ""}`}
                onClick={() => onSelectKp(synthKp.id)}
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
                  s.knowledge_points.map((kp) => {
                    const isCurrent = kp.id === currentKpId;
                    return (
                      <div
                        key={kp.id}
                        className={`tree-row tree-row-kp ${isCurrent ? "is-current" : ""}`}
                        onClick={() => onSelectKp(kp.id)}
                      >
                        <span className="indent" />
                        <span className="indent" />
                        {isCurrent ? (
                          <span
                            className="tree-glyph current"
                            title="当前所在 KP"
                          >
                            ▸
                          </span>
                        ) : (
                          <StatusGlyph status={kp.status} />
                        )}
                        <span className="tree-label">{kp.title}</span>
                      </div>
                    );
                  })}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
});

/* ---------- Turn gauge ---------- */

function TurnGauge({ turn, soft, hard }: { turn: number; soft: number; hard: number }) {
  const pct = Math.min(turn / hard, 1);
  const tickAngle = (soft / hard) * 180;
  return (
    <div className="turn-gauge">
      <svg viewBox="0 0 120 70" width="100%">
        <path
          d="M 12 60 A 48 48 0 0 1 108 60"
          fill="none"
          stroke="var(--paper-3)"
          strokeWidth="6"
          strokeLinecap="round"
        />
        <path
          d="M 12 60 A 48 48 0 0 1 108 60"
          fill="none"
          stroke="var(--accent)"
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={`${pct * 151} 200`}
        />
        <line
          x1={60 + Math.cos(((180 - tickAngle) * Math.PI) / 180) * 42}
          y1={60 - Math.sin(((180 - tickAngle) * Math.PI) / 180) * 42}
          x2={60 + Math.cos(((180 - tickAngle) * Math.PI) / 180) * 54}
          y2={60 - Math.sin(((180 - tickAngle) * Math.PI) / 180) * 54}
          stroke="var(--ink-3)"
          strokeWidth="1.5"
        />
        <text
          x="60"
          y="56"
          textAnchor="middle"
          fontFamily="Newsreader"
          fontSize="22"
          fill="var(--ink-0)"
        >
          {turn}
        </text>
        <text
          x="60"
          y="68"
          textAnchor="middle"
          fontFamily="JetBrains Mono"
          fontSize="8"
          fill="var(--ink-4)"
        >
          / {hard}
        </text>
      </svg>
      <div className="turn-gauge-foot margin-note">软上限 {soft}</div>
    </div>
  );
}

/* ---------- KPPage ---------- */

export function KPPage() {
  const { courseId, kpId } = useParams<{
    courseId: string;
    kpId: string;
  }>();
  const navigate = useNavigate();
  const [meta, setMeta] = useState<LoadState>({ kind: "loading" });
  const [messages, setMessages] = useState<ChatBubble[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryAction, setRetryAction] = useState<(() => void) | null>(null);
  const [keyphrases, setKeyphrases] = useState<string[]>([]);
  const [teacherHasAvatar, setTeacherHasAvatar] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const openedRef = useRef(false);

  // SSE deltas arrive token-by-token. Applying each to state immediately
  // re-renders the whole page and re-parses the streaming bubble's
  // Markdown+KaTeX per token (O(n²) over the answer). Buffer deltas and
  // flush at most once per animation frame — final content is identical.
  const deltaBufRef = useRef<Map<string, string>>(new Map());
  const rafRef = useRef<number | null>(null);

  const flushDeltas = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    const buf = deltaBufRef.current;
    if (buf.size === 0) return;
    deltaBufRef.current = new Map();
    setMessages((prev) =>
      prev.map((m) => {
        const chunk = buf.get(m.key);
        return chunk ? { ...m, content: m.content + chunk } : m;
      }),
    );
  }, []);

  const enqueueDelta = useCallback(
    (key: string, chunk: string) => {
      const buf = deltaBufRef.current;
      buf.set(key, (buf.get(key) ?? "") + chunk);
      if (rafRef.current === null) {
        rafRef.current = requestAnimationFrame(flushDeltas);
      }
    },
    [flushDeltas],
  );

  const cancelDeltas = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    deltaBufRef.current = new Map();
  }, []);

  // Stable identity so the memoized MiniChapterTree doesn't reconcile on
  // every streamed token / composer keystroke.
  const handleSelectKp = useCallback(
    (id: string) => navigate(`/courses/${courseId}/kp/${id}`),
    [navigate, courseId],
  );

  useEffect(() => {
    if (!courseId || !kpId) return;
    let cancelled = false;
    openedRef.current = false;

    // Reset visual state immediately on KP change so the loading overlay
    // (gated on meta.kind === "loading") actually shows, instead of the
    // previous KP's content lingering until new data arrives.
    setMeta({ kind: "loading" });
    setMessages([]);
    setKeyphrases([]);
    setError(null);
    setRetryAction(null);

    Promise.all([
      getChapterTree(courseId),
      listMessages(courseId, kpId),
      getKPContent(courseId, kpId).catch(() => null),
      getTeacherConfig(courseId).catch(() => null),
    ])
      .then(([tree, history, content, teacher]) => {
        if (cancelled) return;
        const found = findKpInTree(tree, kpId);
        if (!found) {
          setMeta({ kind: "not-found" });
          return;
        }
        setMeta({ kind: "ready", tree, kp: found.kp });
        setMessages(history.map(toBubble));
        if (content) setKeyphrases(content.keyphrases);
        setTeacherHasAvatar(teacher?.has_avatar ?? false);

        if (history.length === 0 && !openedRef.current) {
          openedRef.current = true;
          void runOpening(courseId, kpId);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof CoursesError || err instanceof ChatError) {
          setMeta({ kind: "error", message: err.message });
        } else {
          setMeta({ kind: "error", message: "加载失败" });
        }
      });
    return () => {
      cancelled = true;
      cancelDeltas();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId, kpId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
    });
  }, [messages]);

  async function runOpening(cId: string, kId: string) {
    const pendingKey = `pending-opening-${Date.now()}`;
    setSending(true);
    setError(null);
    setRetryAction(null);
    setMessages((prev) => [
      ...prev,
      { key: pendingKey, role: "assistant", content: "", pending: true },
    ]);

    let streamFailed = false;
    const handlers: StreamHandlers = {
      onDelta: (delta) => enqueueDelta(pendingKey, delta),
      onDone: (assistantId) => {
        flushDeltas();
        setMessages((prev) =>
          prev.map((m) =>
            m.key === pendingKey
              ? { ...m, key: assistantId, pending: false }
              : m,
          ),
        );
      },
      onError: (message) => {
        streamFailed = true;
        cancelDeltas();
        setError(message);
        setMessages((prev) => prev.filter((m) => m.key !== pendingKey));
        setRetryAction(() => () => void runOpening(cId, kId));
      },
    };

    await openDialogueStream(cId, kId, handlers);

    if (!streamFailed) {
      flushDeltas();
      setMessages((prev) =>
        prev.map((m) =>
          m.key === pendingKey ? { ...m, pending: false } : m,
        ),
      );
    }
    setSending(false);
  }

  async function handleSend(textOverride?: string) {
    if (!courseId || !kpId) return;
    const text = (textOverride ?? input).trim();
    if (!text || sending) return;

    setError(null);
    setRetryAction(null);
    if (textOverride === undefined) setInput("");
    setSending(true);

    const userKey = `user-${Date.now()}`;
    const pendingKey = `pending-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { key: userKey, role: "user", content: text },
      { key: pendingKey, role: "assistant", content: "", pending: true },
    ]);

    let streamFailed = false;

    await sendMessageStream(courseId, kpId, text, {
      onDelta: (delta) => enqueueDelta(pendingKey, delta),
      onDone: (assistantId) => {
        flushDeltas();
        setMessages((prev) =>
          prev.map((m) =>
            m.key === pendingKey
              ? { ...m, key: assistantId, pending: false }
              : m,
          ),
        );
      },
      onError: (message) => {
        streamFailed = true;
        cancelDeltas();
        setError(message);
        setMessages((prev) =>
          prev.filter((m) => m.key !== pendingKey && m.key !== userKey),
        );
        setRetryAction(() => () => void handleSend(text));
      },
    });

    if (!streamFailed) {
      flushDeltas();
      setMessages((prev) =>
        prev.map((m) =>
          m.key === pendingKey ? { ...m, pending: false } : m,
        ),
      );
    }
    setSending(false);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void handleSend();
    }
  }

  const aiTurns = messages.filter((m) => m.role === "assistant" && !m.pending)
    .length;

  const currentLoc =
    meta.kind === "ready" ? findKpInTree(meta.tree, kpId!) : null;

  // 全书导读/全书总结 are read-only: chat is allowed, but there is no
  // exercise/assessment/pass loop, so hide those entry points.
  const readOnly = meta.kind === "ready" && isSyntheticKp(meta.kp);
  const readOnlyLabel =
    meta.kind === "ready" && kpKind(meta.kp) === "summary"
      ? "全书总结"
      : "全书导读";

  // Loading state takes the full page — return early so the still-mounted
  // dialogue-center (which is rendered always in the main layout) doesn't
  // sit on top of the overlay and hide it.
  if (meta.kind === "loading") {
    return (
      <div className="dialogue-page page-in">
        <div className="dialogue-loading-overlay">
          <div className="dialogue-loading-card">
            <svg
              className="loading-quill"
              viewBox="0 0 48 48"
              width="64"
              height="64"
              aria-hidden="true"
            >
              <g
                stroke="var(--accent)"
                strokeWidth="2"
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M8 40 L26 22" />
                <path
                  d="M26 22 L34 8 L40 14 L26 22 Z"
                  fill="var(--accent-tint)"
                />
              </g>
              <circle cx="7" cy="41" r="1.6" fill="var(--accent)" />
            </svg>
            <div className="serif" style={{ fontSize: 18, color: "var(--ink-0)" }}>
              翻到新一页…
            </div>
            <div className="margin-note" style={{ fontSize: 12 }}>
              老师正在准备这一节的内容
            </div>
            <div className="loading-skeleton-stack">
              <div className="skeleton-line" style={{ width: "60%" }} />
              <div className="skeleton-line" style={{ width: "85%" }} />
              <div className="skeleton-line" style={{ width: "45%" }} />
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="dialogue-page page-in">
      {/* LEFT — mini tree */}
      {meta.kind === "ready" && (
        <aside className="dialogue-left">
          <div className="dialogue-left-head">
            <div
              className="margin-note"
              style={{
                fontSize: 11,
                textTransform: "uppercase",
                letterSpacing: "0.1em",
              }}
            >
              当前位置
            </div>
            <div
              className="serif"
              style={{ fontSize: 16, color: "var(--ink-0)", marginTop: 4 }}
            >
              {meta.kp.title}
            </div>
            <div className="dialogue-crumb mono">
              {currentLoc?.chapter}
              <br />
              <span style={{ color: "var(--ink-5)" }}>›</span>{" "}
              {currentLoc?.section}
            </div>
          </div>
          <div className="tree-scroll" style={{ flex: 1 }}>
            <MiniChapterTree
              tree={meta.tree}
              currentKpId={kpId!}
              onSelectKp={handleSelectKp}
            />
          </div>
          <div className="dialogue-left-foot">
            <button
              type="button"
              className="btn btn-quiet btn-sm"
              onClick={() => navigate(`/courses/${courseId}`)}
            >
              ← 返回章节树
            </button>
          </div>
        </aside>
      )}

      {/* CENTER — dialogue */}
      <section className="dialogue-center">
        {/* Mobile back button */}
        <div className="dialogue-mobile-nav">
          <button
            type="button"
            className="btn btn-quiet btn-sm"
            onClick={() => navigate(`/courses/${courseId}`)}
          >
            ← 返回章节树
          </button>
          {meta.kind === "ready" && (
            <span className="dialogue-mobile-kp-title">{meta.kp.title}</span>
          )}
        </div>
        <div className="dialogue-header">
          <div>
            <div className="margin-note">
              {meta.kind === "ready"
                ? `第 ${aiTurns} 轮 · ${meta.kp.status === "passed" ? "已掌握" : meta.kp.status === "in_progress" ? "学习中" : "未开始"}`
                : "加载中…"}
            </div>
            <h2 style={{ margin: "2px 0 0" }}>
              {meta.kind === "ready" ? meta.kp.title : "…"}
            </h2>
          </div>
          <div className="dialogue-header-actions">
            {readOnly ? (
              <span className="margin-note">只读 · {readOnlyLabel} · 仅对话</span>
            ) : (
              <button
                type="button"
                className="btn btn-accent"
                onClick={() => {
                  if (courseId && kpId) {
                    navigate(`/courses/${courseId}/kp/${kpId}/assessment`);
                  }
                }}
              >
                我懂了，做题去 →
              </button>
            )}
          </div>
        </div>

        <div className="dialogue-stream" ref={scrollRef}>
          <div className="dialogue-stream-inner">
            {messages.map((m, i) => {
              if (m.role === "user") {
                return (
                  <div key={m.key} className="msg msg-user">
                    <div className="msg-bubble msg-bubble-user">
                      {m.content}
                    </div>
                  </div>
                );
              }
              const isFirst =
                i === 0 || messages[i - 1].role === "user";
              return (
                <div key={m.key} className="msg msg-ai">
                  {isFirst && (
                    <div className="msg-ai-mark">
                      {teacherHasAvatar && courseId ? (
                        <img
                          className="mark mark-img"
                          src={teacherAvatarUrl(courseId)}
                          alt=""
                        />
                      ) : (
                        <div className="mark">S</div>
                      )}
                    </div>
                  )}
                  <div className="msg-ai-body">
                    <div className="msg-bubble msg-bubble-ai">
                      {m.content ? (
                        <MarkdownView source={m.content} />
                      ) : m.pending ? (
                        <span className="msg-pending">
                          <svg
                            className="msg-pending-quill"
                            viewBox="0 0 24 24"
                            width="22"
                            height="22"
                          >
                            <g
                              stroke="currentColor"
                              strokeWidth="1.5"
                              fill="none"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            >
                              <path d="M4 20 L13 11" />
                              <path
                                d="M13 11 L16 4 L20 8 L13 11 Z"
                                fill="currentColor"
                              />
                            </g>
                            <circle
                              cx="3.6"
                              cy="20.4"
                              r="0.9"
                              fill="currentColor"
                            />
                          </svg>
                          <span className="msg-pending-text">
                            苏格拉底老师正在备课
                          </span>
                          <span className="thinking-dots">
                            <span />
                            <span />
                            <span />
                          </span>
                        </span>
                      ) : (
                        ""
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="dialogue-composer">
          {error && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.75rem",
                padding: "0 0 12px",
                maxWidth: 720,
                margin: "0 auto",
                color: "var(--accent)",
                fontSize: 13,
              }}
            >
              <span style={{ flex: 1 }}>{error}</span>
              {retryAction && (
                <button
                  type="button"
                  className="btn btn-quiet btn-sm"
                  onClick={() => retryAction()}
                  disabled={sending}
                >
                  重新发送
                </button>
              )}
            </div>
          )}
          <div className="paper-composer">
            <textarea
              className="paper-composer-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="把你的想法写下来，哪怕只是猜测… (⌘ + ↵ 发送)"
              onKeyDown={handleKeyDown}
              rows={2}
              disabled={sending}
            />
            <button
              type="button"
              className="paper-composer-send"
              aria-label="发送"
              disabled={sending || !input.trim()}
              onClick={() => void handleSend()}
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
        </div>
      </section>

      {/* RIGHT — coach rail */}
      {meta.kind === "ready" && (
        <aside className="dialogue-right">
          <div className="card right-card">
            <div className="right-card-title">对话状态</div>
            <TurnGauge turn={aiTurns} soft={20} hard={30} />
            <div className="right-divider" />
            <div className="right-stats">
              <div>
                <div
                  className="margin-note"
                  style={{ fontSize: 11 }}
                >
                  本节预计
                </div>
                <div className="serif" style={{ fontSize: 18 }}>
                  15 分钟
                </div>
              </div>
              <div>
                <div
                  className="margin-note"
                  style={{ fontSize: 11 }}
                >
                  当前轮次
                </div>
                <div className="serif" style={{ fontSize: 18 }}>
                  {aiTurns}
                </div>
              </div>
            </div>
          </div>

          <div className="card right-card">
            <div className="right-card-title">如果你 …</div>
            <div className="rescue-list">
              <button
                type="button"
                className="rescue-btn"
                onClick={() => navigate(`/courses/${courseId}`)}
              >
                <span className="rescue-glyph">☕</span>
                <div>
                  <div>累了，休息一下</div>
                  <div className="margin-note">
                    返回章节树，进度已保存
                  </div>
                </div>
              </button>
              {!readOnly && (
                <button
                  type="button"
                  className="rescue-btn"
                  onClick={() => {
                    if (courseId && kpId)
                      navigate(`/courses/${courseId}/kp/${kpId}/assessment`);
                  }}
                >
                  <span className="rescue-glyph">⏭</span>
                  <div>
                    <div>跳过对话，做作业</div>
                    <div className="margin-note">
                      未通过则进入薄弱点
                    </div>
                  </div>
                </button>
              )}
            </div>
          </div>

          {keyphrases.length > 0 && (
            <div className="card right-card">
              <div className="right-card-title">
                这节课的关键词
              </div>
              <div className="keyphrase-cloud">
                {keyphrases.map((k) => (
                  <span key={k} className="keyphrase">
                    {k}
                  </span>
                ))}
              </div>
            </div>
          )}
        </aside>
      )}
    </div>
  );
}
