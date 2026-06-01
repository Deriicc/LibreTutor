import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  type ApiSettings,
  type TestResult,
  SettingsError,
  getSettings,
  putSettings,
  testChat,
  testEmbedding,
} from "../api/settings";
import { useLanguage, type Lang } from "../i18n/LanguageContext";

const EMPTY: ApiSettings = {
  chat_base_url: "",
  chat_api_key: "",
  chat_model: "",
  chat_provider: "openai",
  embedding_api_key: "",
  embedding_base_url: "",
  embedding_model: "",
  language: "zh",
};

type Probe = { kind: "idle" | "running" | "done"; result?: TestResult };

export function SettingsPage() {
  const { t, setLang } = useLanguage();
  const [form, setForm] = useState<ApiSettings>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [chatProbe, setChatProbe] = useState<Probe>({ kind: "idle" });
  const [embProbe, setEmbProbe] = useState<Probe>({ kind: "idle" });

  useEffect(() => {
    getSettings()
      .then((s) => setForm({ ...EMPTY, ...s }))
      .catch(() => {
        /* keep empty defaults */
      })
      .finally(() => setLoading(false));
  }, []);

  function set<K extends keyof ApiSettings>(k: K, v: ApiSettings[K]) {
    setForm((f) => ({ ...f, [k]: v }));
    setSaved(false);
  }

  function onLanguageChange(v: string) {
    const lang: Lang = v === "en" ? "en" : "zh";
    set("language", lang);
    setLang(lang); // switch the UI immediately
  }

  async function onSave() {
    setSaving(true);
    setSaved(false);
    try {
      const next = await putSettings(form);
      setForm({ ...EMPTY, ...next });
      setSaved(true);
    } catch (e) {
      alert(e instanceof SettingsError ? e.message : t("保存失败"));
    } finally {
      setSaving(false);
    }
  }

  async function probe(
    which: "chat" | "embedding",
    fn: (p: ApiSettings) => Promise<TestResult>,
    setP: (p: Probe) => void,
  ) {
    void which;
    setP({ kind: "running" });
    try {
      setP({ kind: "done", result: await fn(form) });
    } catch (e) {
      setP({
        kind: "done",
        result: {
          ok: false,
          detail: e instanceof SettingsError ? e.message : t("测试失败"),
        },
      });
    }
  }

  if (loading) {
    return (
      <main style={wrap}>
        <p style={{ color: "var(--ink-4)" }}>{t("加载中…")}</p>
      </main>
    );
  }

  return (
    <main style={wrap} className="page-in">
      <div style={{ marginBottom: 18 }}>
        <Link to="/" className="btn btn-quiet btn-sm upload-back-link">
          ← {t("返回")}
        </Link>
      </div>
      <h1 style={{ fontFamily: "var(--serif)", marginBottom: 4 }}>
        {t("设置")}
      </h1>
      <p
        className="margin-note"
        style={{ marginBottom: 24, color: "var(--ink-4)" }}
      >
        {t(
          "系统不再提供公用 Key —— 对话、评分、评估、日记、课程构建均使用你在此填写的 API。未配置 Chat 时这些功能不可用。",
        )}
      </p>

      <section className="card" style={cardStyle}>
        <h2 style={h2}>{t("语言")}</h2>
        <select
          className="input"
          value={form.language}
          onChange={(e) => onLanguageChange(e.target.value)}
        >
          <option value="zh">简体中文</option>
          <option value="en">English</option>
        </select>
        <p className="margin-note" style={hint}>
          {t("界面语言；新建课程的章节树、对话与出题也会使用该语言。")}
        </p>
      </section>

      <section className="card" style={cardStyle}>
        <h2 style={h2}>{t("对话模型（Chat）")}</h2>

        <label className="label">{t("接口格式")}</label>
        <select
          className="input"
          value={form.chat_provider}
          onChange={(e) => set("chat_provider", e.target.value)}
        >
          <option value="openai">{t("OpenAI 兼容")}</option>
          <option value="anthropic">{t("Anthropic 兼容")}</option>
        </select>
        <p className="margin-note" style={hint}>
          {t(
            "两者都通过 OpenAI 兼容客户端调用；选 Anthropic 时请把 Base URL 指向其 OpenAI 兼容代理。",
          )}
        </p>

        <label className="label" style={lbl}>
          Base URL
        </label>
        <input
          className="input"
          placeholder="https://api.deepseek.com"
          value={form.chat_base_url}
          onChange={(e) => set("chat_base_url", e.target.value)}
        />

        <label className="label" style={lbl}>
          API Key
        </label>
        <input
          className="input"
          type="password"
          autoComplete="off"
          placeholder="sk-..."
          value={form.chat_api_key}
          onChange={(e) => set("chat_api_key", e.target.value)}
        />

        <label className="label" style={lbl}>
          {t("模型")}
        </label>
        <input
          className="input"
          placeholder="deepseek-chat"
          value={form.chat_model}
          onChange={(e) => set("chat_model", e.target.value)}
        />

        <div style={{ marginTop: 14 }}>
          <button
            type="button"
            className="btn btn-quiet btn-sm"
            disabled={chatProbe.kind === "running"}
            onClick={() => probe("chat", testChat, setChatProbe)}
          >
            {chatProbe.kind === "running" ? t("测试中…") : t("测试连通性")}
          </button>
          <ProbeMsg probe={chatProbe} />
        </div>
      </section>

      <section className="card" style={cardStyle}>
        <h2 style={h2}>{t("向量模型（Embedding）")}</h2>
        <p className="margin-note" style={hint}>
          {t("可选。留空则用本地哈希向量降级（检索更粗糙，但不依赖外部 Key）。")}
        </p>

        <label className="label" style={lbl}>
          Base URL
        </label>
        <input
          className="input"
          placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
          value={form.embedding_base_url}
          onChange={(e) => set("embedding_base_url", e.target.value)}
        />

        <label className="label" style={lbl}>
          API Key
        </label>
        <input
          className="input"
          type="password"
          autoComplete="off"
          placeholder="sk-..."
          value={form.embedding_api_key}
          onChange={(e) => set("embedding_api_key", e.target.value)}
        />

        <label className="label" style={lbl}>
          {t("模型")}
        </label>
        <input
          className="input"
          placeholder="text-embedding-v4"
          value={form.embedding_model}
          onChange={(e) => set("embedding_model", e.target.value)}
        />

        <div style={{ marginTop: 14 }}>
          <button
            type="button"
            className="btn btn-quiet btn-sm"
            disabled={embProbe.kind === "running"}
            onClick={() =>
              probe("embedding", testEmbedding, setEmbProbe)
            }
          >
            {embProbe.kind === "running" ? t("测试中…") : t("测试连通性")}
          </button>
          <ProbeMsg probe={embProbe} />
        </div>
      </section>

      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <button
          type="button"
          className="btn btn-accent btn-lg"
          disabled={saving}
          onClick={() => void onSave()}
        >
          {saving ? t("保存中…") : t("保存设置")}
        </button>
        {saved && (
          <span style={{ color: "var(--sage)", fontSize: 14 }}>
            ✓ {t("已保存")}
          </span>
        )}
      </div>
    </main>
  );
}

function ProbeMsg({ probe }: { probe: Probe }) {
  if (probe.kind !== "done" || !probe.result) return null;
  const ok = probe.result.ok;
  return (
    <span
      style={{
        marginLeft: 12,
        fontSize: 13,
        color: ok ? "var(--sage)" : "var(--accent)",
      }}
    >
      {ok ? "✓ " : "✗ "}
      {probe.result.detail}
    </span>
  );
}

const wrap: React.CSSProperties = {
  maxWidth: 640,
  margin: "0 auto",
  padding: "40px 24px 80px",
};
const cardStyle: React.CSSProperties = {
  padding: 24,
  marginBottom: 20,
};
const h2: React.CSSProperties = {
  fontFamily: "var(--serif)",
  fontSize: 18,
  marginBottom: 12,
};
const lbl: React.CSSProperties = { marginTop: 14 };
const hint: React.CSSProperties = {
  color: "var(--ink-5)",
  fontSize: 12,
  marginTop: 6,
};
