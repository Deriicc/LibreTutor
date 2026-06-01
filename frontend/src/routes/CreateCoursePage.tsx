import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { CoursesError, createCourse } from "../api/courses";
import { useLanguage } from "../i18n/LanguageContext";

export function CreateCoursePage() {
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [dragActive, setDragActive] = useState(false);

  function validateAndSetFile(candidate: File | null) {
    if (!candidate) return;
    const lower = candidate.name.toLowerCase();
    const ok = [".pdf", ".epub", ".md", ".markdown"].some((ext) => lower.endsWith(ext));
    if (!ok) {
      setError(t("仅支持 .pdf / .epub / .md / .markdown 文件"));
      return;
    }
    setError(null);
    setFile(candidate);
  }

  function onDragEnter(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(true);
  }

  function onDragOver(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(true);
  }

  function onDragLeave(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    e.stopPropagation();
    // Only deactivate when actually leaving the drop zone (not when entering
    // child elements). currentTarget vs relatedTarget check.
    if (
      e.relatedTarget &&
      e.currentTarget.contains(e.relatedTarget as Node)
    ) {
      return;
    }
    setDragActive(false);
  }

  function onDrop(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    const dropped = e.dataTransfer?.files?.[0];
    if (dropped) validateAndSetFile(dropped);
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!file) {
      setError(t("请选择文件"));
      return;
    }
    const lower = file.name.toLowerCase();
    const ok = [".pdf", ".epub", ".md", ".markdown"].some((ext) => lower.endsWith(ext));
    if (!ok) {
      setError(t("仅支持 .pdf / .epub / .md / .markdown 文件"));
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await createCourse(name.trim(), file);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof CoursesError ? err.message : t("创建失败"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main
      className="page-in create-course-page"
      style={{ maxWidth: 920, margin: "0 auto" }}
    >
      <div className="margin-note">{t("新建课程")}</div>
      <h1 style={{ margin: "4px 0 24px" }}>{t("上传一份学习资料")}</h1>

      <form onSubmit={onSubmit}>
        <div className="form-row">
          <label className="label">{t("课程名称")}</label>
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={200}
            placeholder={t("例如：计算机网络期末复习")}
          />
        </div>

        <label
          className={`upload-drop ${dragActive ? "is-drag-active" : ""} ${file ? "is-filled" : ""}`}
          onDragEnter={onDragEnter}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
        >
          <div className="upload-drop-icon" aria-hidden="true">
            {file ? "✓" : dragActive ? "↓" : "⌂"}
          </div>
          <div className="serif" style={{ fontSize: 22, color: "var(--ink-0)" }}>
            {file
              ? file.name
              : dragActive
                ? t("松手放下")
                : t("把 PDF、EPUB 或 Markdown 拖到这里")}
          </div>
          <div className="margin-note">
            {t("或点击选择文件 · 支持 .pdf / .epub / .md / .markdown · 上限 50 MB")}
          </div>
          <input
            id="file-input"
            type="file"
            accept="application/pdf,.pdf,application/epub+zip,.epub,.md,.markdown,text/markdown"
            onChange={(e) => validateAndSetFile(e.target.files?.[0] ?? null)}
            style={{ display: "none" }}
          />
        </label>

        {error && (
          <p style={{ color: "var(--accent)", margin: "12px 0 0" }}>{error}</p>
        )}

        <div style={{ marginTop: 24, display: "flex", gap: 12 }}>
          <button
            type="submit"
            disabled={submitting}
            className="btn btn-accent btn-lg"
          >
            {submitting ? t("上传中…") : t("创建课程")}
          </button>
          <Link to="/" className="btn btn-ghost btn-lg upload-back-link">
            {t("返回书房")}
          </Link>
        </div>
      </form>

      <div className="upload-tips" style={{ marginTop: 48 }}>
        <div className="upload-tip">
          <div className="upload-tip-num mono">01</div>
          <div>
            <div className="serif upload-tip-title">
              {t("章节树将基于你的目录")}
            </div>
            <div className="margin-note">
              {t(
                "系统抽取 PDF outline 作为章/节骨架，再让 LLM 把每一节切分成 1–3 个聚焦单一概念的 KP。",
              )}
            </div>
          </div>
        </div>
        <div className="upload-tip">
          <div className="upload-tip-num mono">02</div>
          <div>
            <div className="serif upload-tip-title">{t("生成所需时间根据文本长度决定")}</div>
            <div className="margin-note">
              {t("期间会同时切片 PDF 并建立向量索引。可以离开页面，完成后会自动刷新。")}
            </div>
          </div>
        </div>
        <div className="upload-tip">
          <div className="upload-tip-num mono">03</div>
          <div>
            <div className="serif upload-tip-title">{t("章节树生成后不可改")}</div>
            <div className="margin-note">
              {t("如对结果不满意，可以重新上传以重建。这是为了保证学习路径的稳定性。")}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
