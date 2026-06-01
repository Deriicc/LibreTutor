import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CoursesError, deleteCourse, listCourses } from "../api/courses";
import type { Course } from "../api/courses";
import { useLanguage } from "../i18n/LanguageContext";

type ListState =
  | { kind: "loading" }
  | { kind: "ready"; courses: Course[] }
  | { kind: "error"; message: string };

const SPINE_COLORS = ["#8a3324", "#5c7148", "#2a4a6a", "#a8761d", "#6b4c7a"];

function getSpineColor(index: number): string {
  return SPINE_COLORS[index % SPINE_COLORS.length];
}

function formatStatus(status: Course["generation_status"]): string {
  switch (status) {
    case "pending":
      return "等待中";
    case "running":
      return "生成中";
    case "done":
      return "加载完成";
    case "failed":
      return "失败";
  }
}

export function HomePage() {
  const { t } = useLanguage();
  const [list, setList] = useState<ListState>({ kind: "loading" });
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listCourses()
      .then((courses) => {
        if (!cancelled) setList({ kind: "ready", courses });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof CoursesError ? err.message : t("加载失败");
        setList({ kind: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleDelete(course: Course) {
    if (!window.confirm(t("确定删除「{name}」？此操作不可恢复。", { name: course.name }))) return;
    setDeletingId(course.id);
    try {
      await deleteCourse(course.id);
      setList((prev) =>
        prev.kind === "ready"
          ? { kind: "ready", courses: prev.courses.filter((c) => c.id !== course.id) }
          : prev,
      );
    } catch (err) {
      const message = err instanceof CoursesError ? err.message : t("删除失败");
      window.alert(message);
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <main
      className="page-in home-page"
      style={{ padding: "clamp(20px, 4vw, 40px) clamp(16px, 3vw, 32px) 80px", width: "100%", maxWidth: 1240, margin: "0 auto" }}
    >
      <div style={{ marginBottom: 16 }}>
        <div className="margin-note" style={{ marginBottom: 4 }}>
          {t("欢迎回来")}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 24,
          }}
        >
          <h1 style={{ margin: 0 }}>{t("我的课程")}</h1>
          <Link
            to="/courses/new"
            className="btn-add"
            title={t("新建一门课")}
            aria-label={t("新建一门课")}
          >
            +
          </Link>
        </div>
      </div>
      <div className="book-rule" />

      {list.kind === "loading" && (
        <div className="course-shelf">
          {[0, 1].map((i) => (
            <div key={i} className="course-card" style={{ minHeight: 240 }}>
              <div className="skel" style={{ height: 110 }} />
              <div style={{ padding: 16 }}>
                <div className="skel" style={{ height: 20, width: "70%", marginBottom: 8 }} />
                <div className="skel" style={{ height: 14, width: "40%" }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {list.kind === "error" && (
        <p style={{ color: "var(--accent)" }}>{list.message}</p>
      )}

      {list.kind === "ready" && list.courses.length === 0 && (
        <div className="course-shelf">
          <Link to="/courses/new" className="course-card course-card-add">
            <div className="add-plus">+</div>
            <div className="serif" style={{ fontSize: 17 }}>
              {t("上传一份新资料")}
            </div>
            <div className="margin-note" style={{ textAlign: "center" }}>
              {t("PDF · 支持目录解析")}
              <br />
              {t("生成章节树")}
            </div>
          </Link>
        </div>
      )}

      {list.kind === "ready" && list.courses.length > 0 && (
        <div className="course-shelf">
          {list.courses.map((c, idx) => {
            const stripe = getSpineColor(idx);
            const kpPct =
              c.kp_total > 0 ? Math.round((c.kp_passed / c.kp_total) * 100) : 0;
            const genPct =
              c.progress_total > 0
                ? Math.round((c.progress_done / c.progress_total) * 100)
                : 0;
            const isDone = c.generation_status === "done";
            const progressPct = isDone ? kpPct : genPct;
            return (
              <div key={c.id} className="course-card" style={{ position: "relative" }}>
                <Link
                  to={`/courses/${c.id}`}
                  style={{
                    textDecoration: "none",
                    color: "inherit",
                    display: "flex",
                    flexDirection: "column",
                    flex: 1,
                  }}
                >
                  <div className="course-spine" style={{ background: stripe }}>
                    <div className="course-spine-title serif">{c.name}</div>
                  </div>
                  <div className="course-body">
                    <div className="course-title">{c.name}</div>
                    <div className="course-sub">
                      {t(formatStatus(c.generation_status))} ·{" "}
                      {new Date(c.created_at).toLocaleDateString()}
                    </div>
                    <div className="course-meta">
                      <span className="mono tnum">{progressPct}%</span>
                      <span className="course-progress-track">
                        <span
                          className="course-progress-fill"
                          style={{
                            width: `${progressPct}%`,
                            background: stripe,
                          }}
                        />
                      </span>
                    </div>
                    <div className="course-stats">
                      {isDone ? (
                        <div>
                          <span className="mono tnum">{c.kp_passed}</span>
                          <span className="ink-4">/{c.kp_total} {t("个知识点")}</span>
                          <span className="ink-4">{t("已掌握")}</span>
                        </div>
                      ) : (
                        <>
                          <div>
                            <span className="mono tnum">{c.progress_done}</span>
                            <span className="ink-4">/{c.progress_total} {t("节")}</span>
                          </div>
                          <div className="ink-4">
                            {c.generation_status === "running"
                              ? t("生成中…")
                              : c.generation_status === "failed"
                                ? t("生成失败")
                                : t("等待中")}
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                </Link>
                <button
                  type="button"
                  onClick={() => void handleDelete(c)}
                  disabled={deletingId === c.id}
                  className="btn btn-quiet btn-sm"
                  style={{
                    position: "absolute",
                    top: 8,
                    right: 8,
                    opacity: 0.7,
                  }}
                >
                  {deletingId === c.id ? t("删除中…") : t("删除")}
                </button>
              </div>
            );
          })}
          <Link to="/courses/new" className="course-card course-card-add">
            <div className="add-plus">+</div>
            <div className="serif" style={{ fontSize: 17 }}>
              {t("上传一份新资料")}
            </div>
            <div className="margin-note" style={{ textAlign: "center" }}>
              {t("PDF · 支持目录解析")}
              <br />
              {t("生成章节树")}
            </div>
          </Link>
        </div>
      )}
    </main>
  );
}
