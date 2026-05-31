import "katex/dist/katex.min.css";
import { memo, useDeferredValue } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkBreaks from "remark-breaks";
import remarkMath from "remark-math";

type Props = {
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  placeholder?: string;
  rows?: number;
};

const TEXTAREA_STYLE: React.CSSProperties = {
  width: "100%",
  padding: "0.5rem",
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: "0.95rem",
  border: "1px solid #d1d5db",
  borderRadius: 6,
  boxSizing: "border-box",
  resize: "vertical",
};

const PREVIEW_STYLE: React.CSSProperties = {
  padding: "0.5rem 0.75rem",
  marginTop: "0.5rem",
  background: "#f9fafb",
  border: "1px dashed #d1d5db",
  borderRadius: 6,
  fontSize: "0.95rem",
  minHeight: "2.5rem",
  color: "#111827",
};

const HINT_STYLE: React.CSSProperties = {
  marginTop: "0.25rem",
  color: "#6b7280",
  fontSize: "0.75rem",
};

export function RichTextEditor({
  value,
  onChange,
  disabled = false,
  placeholder,
  rows = 4,
}: Props) {
  // Keep keystrokes responsive: the textarea updates immediately while the
  // Markdown+KaTeX preview re-parses at a deferred, non-blocking priority.
  const deferredValue = useDeferredValue(value);
  return (
    <div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        rows={rows}
        placeholder={
          placeholder ??
          "支持 Markdown：**粗体** *斜体* - 列表  +  行内公式 $a^2+b^2=c^2$"
        }
        style={TEXTAREA_STYLE}
      />
      <p style={HINT_STYLE}>
        提示：行内公式用 <code>$...$</code>；块级公式用 <code>$$...$$</code>。
      </p>
      {deferredValue.trim() && (
        <div style={PREVIEW_STYLE} aria-label="预览">
          <ReactMarkdown
            remarkPlugins={[remarkMath]}
            rehypePlugins={[rehypeKatex]}
          >
            {deferredValue}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}

export const MarkdownView = memo(function MarkdownView({
  source,
}: {
  source: string;
}) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkMath, remarkBreaks]}
      rehypePlugins={[rehypeKatex]}
    >
      {source}
    </ReactMarkdown>
  );
});
