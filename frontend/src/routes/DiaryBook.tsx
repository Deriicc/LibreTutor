import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { DiaryError, getCourseDiary } from "../api/diary";
import type { CourseDiary, DiaryEntry } from "../api/diary";
import { useLanguage } from "../i18n/LanguageContext";
import { et, currentLang } from "../i18n/translations";

// ─────────────────────────────────────────────────────────
// Adapted view-model: enrich the API entries with the
// presentation fields the handoff design relies on
// (folio number, dateCN, ink colour derived from author).
// ─────────────────────────────────────────────────────────
type Ink = "oxblood" | "sage";

type AuthorView = {
  label: string;
  sig: string;
  stamp: string;
  ink: Ink;
};

type EntryView = {
  raw: DiaryEntry;
  folio: number;
  isPending: boolean;
  bodyParas: string[];
  date: string; // "2026-05-14"
  dateShort: string; // "05 · 14"
  dateCN: string; // "五月十四日"
  author: AuthorView;
  lastByAuthor: boolean;
};

const CN_DIGITS = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"];

function cnNumber(n: number): string {
  if (n <= 10) return n === 10 ? "十" : CN_DIGITS[n];
  if (n < 20) return "十" + CN_DIGITS[n - 10];
  if (n < 100) {
    const tens = Math.floor(n / 10);
    const ones = n % 10;
    return CN_DIGITS[tens] + "十" + (ones ? CN_DIGITS[ones] : "");
  }
  return String(n);
}

function toDateCN(iso: string | null): string {
  if (currentLang() === "en") return "";
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${cnNumber(d.getMonth() + 1)}月${cnNumber(d.getDate())}日`;
}

function toDateShort(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${m} · ${day}`;
}

function toIsoDay(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "";
}

function authorViewFor(entry: DiaryEntry): AuthorView {
  const label = entry.author_label?.trim() || et("老师");
  const sig = entry.author_signature?.trim() || label;
  const stamp = Array.from(label)[0] ?? et("师");
  // ink: stable per author label (oxblood by default, sage for "second" author)
  let h = 0;
  for (const ch of label) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const ink: Ink = h % 2 === 0 ? "oxblood" : "sage";
  return { label, sig, stamp, ink };
}

function buildView(diary: CourseDiary): EntryView[] {
  const entries = diary.entries;
  return entries.map((e, i) => {
    const isPending = e.status !== "done" || !e.body;
    const bodyParas = e.body
      ? e.body
          .split(/\n{2,}/)
          .map((p) => p.trim())
          .filter(Boolean)
      : [];
    const author = authorViewFor(e);
    const next = entries[i + 1];
    const lastByAuthor =
      !next || (next.author_label ?? "") !== (e.author_label ?? "");
    return {
      raw: e,
      folio: i + 1,
      isPending,
      bodyParas,
      date: toIsoDay(e.created_at),
      dateShort: toDateShort(e.created_at),
      dateCN: toDateCN(e.created_at),
      author,
      lastByAuthor,
    };
  });
}

// ─────────────────────────────────────────────────────────
// DiaryBook — Teacher's Diary Book
// 1:1 layout port of handoff/src/screen-diary.jsx
// ─────────────────────────────────────────────────────────
type State =
  | { kind: "loading" }
  | { kind: "ready"; diary: CourseDiary }
  | { kind: "error"; message: string };

export function DiaryBook() {
  const { t } = useLanguage();
  const { courseId } = useParams<{ courseId: string }>();
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    if (!courseId) return;
    let cancelled = false;
    getCourseDiary(courseId)
      .then((diary) => {
        if (!cancelled) setState({ kind: "ready", diary });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof DiaryError ? err.message : t("加载失败");
        setState({ kind: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  if (state.kind === "loading") {
    return (
      <main className="diary-page-root page-in">
        <div className="margin-note">{t("翻开日记本…")}</div>
      </main>
    );
  }
  if (state.kind === "error") {
    return (
      <main className="diary-page-root page-in">
        <p style={{ color: "var(--accent)" }}>{state.message}</p>
      </main>
    );
  }

  return <DiaryReady diary={state.diary} courseId={courseId} />;
}

function DiaryReady({
  diary,
  courseId,
}: {
  diary: CourseDiary;
  courseId: string | undefined;
}) {
  const { t } = useLanguage();
  const view = useMemo(() => buildView(diary), [diary]);

  // Open the most-recent *written* entry by default (skip pending).
  const lastWritten = useMemo(() => {
    for (let i = view.length - 1; i >= 0; i--) {
      if (!view[i].isPending) return i;
    }
    return Math.max(0, view.length - 1);
  }, [view]);

  const [idx, setIdx] = useState(lastWritten);
  const [turning, setTurning] = useState(false);

  // If `lastWritten` shifts because data refreshed, snap to it.
  useEffect(() => {
    setIdx((cur) => Math.min(cur, Math.max(0, view.length - 1)));
  }, [view.length]);

  // Animate page-turn on entry change
  useEffect(() => {
    setTurning(true);
    const t = window.setTimeout(() => setTurning(false), 320);
    return () => window.clearTimeout(t);
  }, [idx]);

  // Keyboard navigation
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && target.matches("input, textarea")) return;
      if (e.key === "ArrowLeft" && idx > 0) setIdx(idx - 1);
      if (e.key === "ArrowRight" && idx < view.length - 1) setIdx(idx + 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [idx, view.length]);

  if (view.length === 0) {
    return (
      <main className="diary-page-root page-in">
        <DiaryHead
          courseName={diary.course_name}
          writtenCount={0}
          authorCount={0}
        />
        <div className="diary-body" style={{ gridTemplateColumns: "1fr" }}>
          <div className="diary-spread">
            <div className="diary-pending">
              <div className="diary-pending-glyph" aria-hidden>
                ✒︎
              </div>
              <div className="diary-pending-text">{t("日记本还是空的。")}</div>
              <div className="diary-pending-hint">
                {t("等老师在第一节课后落笔，这里就会有第一篇。")}
              </div>
            </div>
          </div>
        </div>
      </main>
    );
  }

  const entry = view[idx];
  const writtenCount = view.filter((e) => !e.isPending).length;
  const authorSet = new Set(
    view.map((e) => e.author.label).filter((l) => Boolean(l)),
  );

  return (
    <main className="diary-page-root page-in">
      <DiaryHead
        courseName={diary.course_name}
        writtenCount={writtenCount}
        authorCount={authorSet.size}
      />

      <div className="diary-body">
        <DiaryTOC view={view} idx={idx} onPick={setIdx} />

        <div className={`diary-spread ${turning ? "turning" : ""}`}>
          {entry.isPending ? (
            <DiaryPending entry={entry} />
          ) : (
            <DiaryEntryView entry={entry} />
          )}
          <DiaryPageFooter entry={entry} total={view.length} />
        </div>

        <DiaryMargin entry={entry} courseId={courseId} />
      </div>

      <DiaryNav view={view} idx={idx} onPick={setIdx} />
    </main>
  );
}

// ─────────────────────────────────────────────────────────
// Header
// ─────────────────────────────────────────────────────────
function DiaryHead({
  courseName,
  writtenCount,
  authorCount,
}: {
  courseName: string;
  writtenCount: number;
  authorCount: number;
}) {
  const { t } = useLanguage();
  return (
    <header className="diary-head">
      <div>
        <div className="diary-eyebrow">{t("A Teacher's Journal · 教师手记")}</div>
        <h1 className="serif">{courseName}</h1>
        <div className="diary-subtitle">
          {t("每一节课结束后，老师在这本日记里写下当晚的复盘。")}
        </div>
      </div>
      <div className="diary-head-meta">
        <span className="num serif tnum">{writtenCount}</span>
        <span className="num-unit">{t("篇已成稿")}</span>
        <div style={{ marginTop: 4 }}>{t("共 {n} 位执笔人", { n: authorCount })}</div>
        <div className="diary-head-ornament">❦ ❦ ❦</div>
      </div>
    </header>
  );
}

// ─────────────────────────────────────────────────────────
// Left rail — TOC (chronological)
// ─────────────────────────────────────────────────────────
function DiaryTOC({
  view,
  idx,
  onPick,
}: {
  view: EntryView[];
  idx: number;
  onPick: (i: number) => void;
}) {
  const { t } = useLanguage();
  return (
    <nav className="diary-toc">
      <div className="diary-toc-title">{t("编年索引")}</div>
      <div className="diary-toc-list">
        {view.map((e, i) => {
          const isActive = i === idx;
          const isPending = e.isPending;
          return (
            <button
              key={`${e.raw.kp_id}-${e.raw.attempt}`}
              type="button"
              className={`diary-toc-item ${isActive ? "active" : ""} ${
                isPending ? "pending" : ""
              }`}
              onClick={() => onPick(i)}
            >
              <span
                className={`diary-toc-stamp ${
                  isPending ? "ink-pending" : `ink-${e.author.ink}`
                }`}
                aria-hidden
              />
              <span>
                <div className="diary-toc-date">{e.dateShort || "—"}</div>
                <div className="diary-toc-kp">{e.raw.kp_title}</div>
                <div className="diary-toc-aux">
                  <span>{e.author.label}</span>
                  {e.raw.attempt > 1 && (
                    <span className="retry-tag">retry · {e.raw.attempt}</span>
                  )}
                  {isPending && <span>{t("· 未提笔")}</span>}
                </div>
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}

// ─────────────────────────────────────────────────────────
// One entry's body
// ─────────────────────────────────────────────────────────
function DiaryEntryView({ entry }: { entry: EntryView }) {
  const { t } = useLanguage();
  const paras = entry.bodyParas;

  // Insert a fleuron between the 2nd and 3rd paragraph for rhythm.
  const renderBody = () => {
    const out: JSX.Element[] = [];
    paras.forEach((p, i) => {
      if (i === 0 && p) {
        const first = Array.from(p)[0] ?? "";
        const rest = p.slice(first.length);
        out.push(
          <p key={`p-${i}`} className="has-dropcap">
            <span className="dropcap-char">{first}</span>
            {rest}
          </p>,
        );
      } else {
        out.push(<p key={`p-${i}`}>{p}</p>);
      }
      if (paras.length >= 4 && i === Math.floor(paras.length / 2) - 1) {
        out.push(
          <div key={`f-${i}`} className="diary-fleuron" aria-hidden>
            <span>❦</span>
          </div>,
        );
      }
    });
    return out;
  };

  return (
    <article>
      <div className="diary-entry-top">
        <div className="diary-entry-eyebrow">
          <span>{t("复盘")}</span>
        </div>
        <div className="diary-entry-folio">
          {entry.raw.attempt > 1 && (
            <span
              className="retry-chip"
              title={t("第 {n} 次执笔", { n: entry.raw.attempt })}
            >
              {t("retry · 第 {n} 次", { n: entry.raw.attempt })}
            </span>
          )}
          <span className="roman">Folio</span> · {t("第 {n} 篇", { n: entry.folio })}
        </div>
      </div>

      <h2 className="diary-entry-date">
        <span className="diary-entry-date-cn serif">
          {entry.dateCN || entry.date}
        </span>
      </h2>
      <div className="diary-entry-kp">{t("关于「{title}」", { title: entry.raw.kp_title })}</div>

      <div className="diary-entry-body">{renderBody()}</div>

      <div className="diary-sign">
        <div className="diary-sign-text">
          <div className={`diary-sign-name ink-${entry.author.ink}`}>
            {entry.author.sig}
          </div>
          <div className="diary-sign-postscript">
            {entry.lastByAuthor
              ? t("— 这是我在这本日记里的最后一笔。")
              : t("— {date}　灯下记。", { date: entry.dateCN || entry.date })}
          </div>
        </div>
      </div>
    </article>
  );
}

// ─────────────────────────────────────────────────────────
// Pending entry — quill not yet to paper
// ─────────────────────────────────────────────────────────
function DiaryPending({ entry }: { entry: EntryView }) {
  const { t } = useLanguage();
  const status = entry.raw.status;
  const hint =
    status === "failed"
      ? t("上次没写完，老师稍后会回来补上这一笔。")
      : status === "running"
        ? t("今夜尚未提笔——老师还在桌前推敲措辞。")
        : t("这一节她还在路上。等这堂课结束，{author}会回到桌前，把今晚的事写下来。", { author: entry.author.label });

  return (
    <article>
      <div className="diary-entry-top">
        <div className="diary-entry-eyebrow">
          <span>{t("对话进行中")}</span>
        </div>
        <div className="diary-entry-folio">
          <span className="roman">Folio</span> · {t("第 {n} 篇", { n: entry.folio })}
        </div>
      </div>

      <div className="diary-pending">
        <div className="diary-pending-glyph" aria-hidden>
          ✒︎
        </div>
        <div className="diary-pending-text">{t("今夜尚未提笔。")}</div>
        <div className="diary-pending-hint">{hint}</div>
        <div className="diary-pending-author">
          {t("预计执笔　·　{author}", { author: entry.author.label })}
        </div>
      </div>
    </article>
  );
}

// ─────────────────────────────────────────────────────────
// Page footer ornament + folio
// ─────────────────────────────────────────────────────────
function DiaryPageFooter({
  entry,
  total,
}: {
  entry: EntryView;
  total: number;
}) {
  return (
    <div className="diary-page-footer" aria-hidden>
      <span>{entry.date || "—"}</span>
      <span className="ornament">
        <span>·</span>
        <span>❦</span>
        <span>·</span>
      </span>
      <span>
        {entry.folio} / {total}
      </span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// Right rail — margin notes (pencil annotations)
// ─────────────────────────────────────────────────────────
function DiaryMargin({
  entry,
  courseId,
}: {
  entry: EntryView;
  courseId: string | undefined;
}) {
  const { t } = useLanguage();
  const navigate = useNavigate();
  const isPending = entry.isPending;

  const goToKp = () => {
    if (!courseId) return;
    navigate(`/courses/${courseId}/kp/${entry.raw.kp_id}`);
  };
  const goHome = () => navigate("/");

  return (
    <aside className="diary-margin">
      <div className="diary-margin-title">{t("边 · 注")}</div>

      {isPending && (
        <div className="diary-margin-block">
          <div className="diary-margin-key">{t("此刻")}</div>
          <div className="diary-margin-val">
            {entry.raw.status === "failed"
              ? t("上次写到一半搁笔了。")
              : entry.raw.status === "running"
                ? t("老师正在写这一篇…")
                : t("这一节还没落笔。")}
          </div>
          <div className="diary-margin-pencil">
            {t("等她说出“好像懂了”，今晚的日记才会开始写。")}
          </div>
        </div>
      )}

      <div className="diary-margin-actions">
        <button
          type="button"
          className="diary-margin-link"
          onClick={goHome}
        >
          <span className="diary-margin-link-line" aria-hidden />
          <span className="diary-margin-link-inner">
            <span className="diary-margin-link-label">{t("返回主页")}</span>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
              <polyline points="9 22 9 12 15 12 15 22" />
            </svg>
          </span>
        </button>
        <button
          type="button"
          className="diary-margin-link"
          onClick={goToKp}
        >
          <span className="diary-margin-link-line" aria-hidden />
          <span className="diary-margin-link-inner">
            <span className="diary-margin-link-label">{t("返回该章节")}</span>
            <span className="diary-margin-link-kp" title={entry.raw.kp_title}>
              {entry.raw.kp_title}
            </span>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
          </span>
        </button>
      </div>
    </aside>
  );
}

// ─────────────────────────────────────────────────────────
// Bottom nav (prev/next + folio + kbd hint)
// ─────────────────────────────────────────────────────────
function DiaryNav({
  view,
  idx,
  onPick,
}: {
  view: EntryView[];
  idx: number;
  onPick: (i: number) => void;
}) {
  const prev = idx > 0 ? view[idx - 1] : null;
  const next = idx < view.length - 1 ? view[idx + 1] : null;
  // satisfy a tsc unused-imports lint check on useRef when stripping
  const { t } = useLanguage();
  const _r = useRef<unknown>(null);
  void _r;

  return (
    <footer className="diary-nav">
      <div className="diary-nav-side left">
        <button
          type="button"
          className="diary-nav-btn"
          disabled={!prev}
          onClick={() => prev && onPick(idx - 1)}
        >
          <span className="arrow">←</span>
          <span>
            {t("上一篇")}
            {prev && (
              <span className="peek">
                {prev.dateCN || prev.date} · {prev.raw.kp_title}
              </span>
            )}
          </span>
        </button>
      </div>

      <div className="diary-nav-folio">
        <span>{t("第")}</span>
        <span className="num serif tnum">{idx + 1}</span>
        <span>{t("篇 / 共 {n} 篇", { n: view.length })}</span>
        <span className="kbd">
          {t("翻页")} <kbd>←</kbd>
          <kbd>→</kbd>
        </span>
      </div>

      <div className="diary-nav-side right">
        <button
          type="button"
          className="diary-nav-btn"
          disabled={!next}
          onClick={() => next && onPick(idx + 1)}
          style={{ flexDirection: "row-reverse" }}
        >
          <span className="arrow">→</span>
          <span style={{ textAlign: "right" }}>
            {t("下一篇")}
            {next && (
              <span className="peek">
                {next.dateCN || next.date} · {next.raw.kp_title}
              </span>
            )}
          </span>
        </button>
      </div>
    </footer>
  );
}
