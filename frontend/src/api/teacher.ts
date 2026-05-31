export type TeacherConfig = {
  scene: string;
  learner_context: string;
  has_generated_few_shots: boolean;
  scene_dirty: boolean;
  has_avatar: boolean;
};

export type TeacherConfigPayload = {
  scene: string;
  learner_context: string;
};

export class TeacherConfigError extends Error {
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
  throw new TeacherConfigError(res.status, detail);
}

export async function getTeacherConfig(
  courseId: string,
): Promise<TeacherConfig> {
  return asJson<TeacherConfig>(
    await fetch(`/api/courses/${courseId}/teacher-config`, {
      credentials: "include",
    }),
  );
}

export async function putTeacherConfig(
  courseId: string,
  payload: TeacherConfigPayload,
): Promise<TeacherConfig> {
  return asJson<TeacherConfig>(
    await fetch(`/api/courses/${courseId}/teacher-config`, {
      method: "PUT",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function uploadTeacherAvatar(
  courseId: string,
  file: File,
): Promise<TeacherConfig> {
  const form = new FormData();
  form.append("file", file);
  return asJson<TeacherConfig>(
    await fetch(`/api/courses/${courseId}/teacher-config/avatar`, {
      method: "PUT",
      credentials: "include",
      body: form,
    }),
  );
}

export function teacherAvatarUrl(courseId: string, bust?: number): string {
  const base = `/api/courses/${courseId}/teacher-config/avatar`;
  return bust ? `${base}?t=${bust}` : base;
}

export async function regenerateFewShots(
  courseId: string,
): Promise<TeacherConfig> {
  return asJson<TeacherConfig>(
    await fetch(
      `/api/courses/${courseId}/teacher-config/regenerate-few-shots`,
      {
        method: "POST",
        credentials: "include",
      },
    ),
  );
}

export type TestChatMessage = { role: "user" | "assistant"; content: string };

export type TestChatHandlers = {
  onDelta: (delta: string) => void;
  onDone: () => void;
  onError: (message: string) => void;
};

export async function streamTestChat(
  courseId: string,
  messages: TestChatMessage[],
  handlers: TestChatHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(
      `/api/courses/${courseId}/teacher-config/test-chat`,
      {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ messages }),
        signal,
      },
    );
  } catch (err) {
    if ((err as { name?: string })?.name === "AbortError") return;
    handlers.onError("网络错误");
    return;
  }

  if (!res.ok || !res.body) {
    let message = `请求失败 (HTTP ${res.status})`;
    try {
      const errBody = (await res.json()) as { detail?: unknown };
      if (typeof errBody.detail === "string") message = errBody.detail;
    } catch {
      // ignore
    }
    handlers.onError(message);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep = buffer.indexOf("\n\n");
      while (sep >= 0) {
        const raw = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        sep = buffer.indexOf("\n\n");
        let eventName = "message";
        let dataLine = "";
        for (const line of raw.split("\n")) {
          if (line.startsWith("event:")) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            dataLine += line.slice(5).trimStart();
          }
        }
        if (!dataLine) continue;
        try {
          const parsed = JSON.parse(dataLine) as {
            delta?: string;
            message?: string;
          };
          if (eventName === "error") {
            handlers.onError(parsed.message ?? "未知错误");
            return;
          }
          if (eventName === "done") {
            handlers.onDone();
            return;
          }
          if (typeof parsed.delta === "string") {
            handlers.onDelta(parsed.delta);
          }
        } catch {
          // ignore malformed event
        }
      }
    }
  } catch (err) {
    if ((err as { name?: string })?.name === "AbortError") return;
    handlers.onError("流式读取异常");
  }
}
