import { et } from "../i18n/translations";

export type MessageRole = "user" | "assistant";

export type ChatMessage = {
  id: string;
  role: MessageRole;
  content: string;
  created_at: string;
};

export class ChatError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function listMessages(
  courseId: string,
  kpId: string,
): Promise<ChatMessage[]> {
  const res = await fetch(
    `/api/courses/${courseId}/kp/${kpId}/messages`,
    { credentials: "include" },
  );
  if (!res.ok) {
    throw new ChatError(res.status, et("加载消息失败 (HTTP {status})", { status: res.status }));
  }
  return (await res.json()) as ChatMessage[];
}

export type StreamHandlers = {
  onDelta: (delta: string) => void;
  onDone: (assistantMessageId: string) => void;
  onError: (message: string) => void;
};

async function _parseSSE(
  body: ReadableStream<Uint8Array>,
  handlers: StreamHandlers,
): Promise<void> {
  const reader = body.getReader();
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
            id?: string;
            message?: string;
          };
          if (eventName === "error") {
            handlers.onError(parsed.message ?? et("未知错误"));
            return;
          }
          if (eventName === "done") {
            if (parsed.id) handlers.onDone(parsed.id);
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
    handlers.onError(et("流式读取异常"));
  }
}

async function _postStream(
  url: string,
  body: BodyInit | null,
  headers: Record<string, string>,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      credentials: "include",
      headers,
      body,
      signal,
    });
  } catch (err) {
    if ((err as { name?: string })?.name === "AbortError") return;
    handlers.onError(et("网络错误"));
    return;
  }

  if (!res.ok || !res.body) {
    let message = et("请求失败 (HTTP {status})", { status: res.status });
    try {
      const errBody = (await res.json()) as { detail?: unknown };
      if (typeof errBody.detail === "string") message = errBody.detail;
    } catch {
      // ignore
    }
    handlers.onError(message);
    return;
  }

  await _parseSSE(res.body, handlers);
}

export async function sendMessageStream(
  courseId: string,
  kpId: string,
  content: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  await _postStream(
    `/api/courses/${courseId}/kp/${kpId}/messages`,
    JSON.stringify({ content }),
    { "content-type": "application/json" },
    handlers,
    signal,
  );
}

export async function openDialogueStream(
  courseId: string,
  kpId: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  await _postStream(
    `/api/courses/${courseId}/kp/${kpId}/messages/opening`,
    null,
    {},
    handlers,
    signal,
  );
}
