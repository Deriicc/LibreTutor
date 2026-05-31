export type ApiSettings = {
  chat_base_url: string;
  chat_api_key: string;
  chat_model: string;
  chat_provider: string;
  embedding_api_key: string;
  embedding_base_url: string;
  embedding_model: string;
};

export type TestResult = { ok: boolean; detail: string };

export class SettingsError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function asJson<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T;
  let detail = `HTTP ${res.status}`;
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    // ignore
  }
  throw new SettingsError(res.status, detail);
}

export async function getSettings(): Promise<ApiSettings> {
  return asJson<ApiSettings>(
    await fetch("/api/settings", { credentials: "include" }),
  );
}

export async function putSettings(
  payload: ApiSettings,
): Promise<ApiSettings> {
  return asJson<ApiSettings>(
    await fetch("/api/settings", {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function testChat(
  payload: ApiSettings,
): Promise<TestResult> {
  return asJson<TestResult>(
    await fetch("/api/settings/test-chat", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function testEmbedding(
  payload: ApiSettings,
): Promise<TestResult> {
  return asJson<TestResult>(
    await fetch("/api/settings/test-embedding", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}
