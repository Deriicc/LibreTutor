export type GenerationStatus = "pending" | "running" | "done" | "failed";

export type Course = {
  id: string;
  name: string;
  created_at: string;
  generation_status: GenerationStatus;
  generation_error: string | null;
  progress_done: number;
  progress_total: number;
  kp_passed: number;
  kp_total: number;
};

export type KPStatus = "untouched" | "in_progress" | "passed";

export type KnowledgePointNode = {
  id: string;
  title: string;
  status: KPStatus;
  boundary: Record<string, unknown>;
  order_index: number;
};

/** "overview" | "summary" for the synthetic 全书导读/全书总结 KPs,
 * else null. These are read-only: chat is allowed, but there is no
 * exercise/assessment/pass loop and they don't count toward progress. */
export function kpKind(kp: KnowledgePointNode): string | null {
  const k = (kp.boundary as { kind?: unknown } | null)?.kind;
  return typeof k === "string" ? k : null;
}

export function isSyntheticKp(kp: KnowledgePointNode): boolean {
  return kpKind(kp) !== null;
}

export type SectionNode = {
  id: string;
  title: string;
  order_index: number;
  status: KPStatus;
  knowledge_points: KnowledgePointNode[];
};

export type ChapterNode = {
  id: string;
  title: string;
  order_index: number;
  status: KPStatus;
  sections: SectionNode[];
};

/** The synthetic 全书导读/全书总结 KP is stored as a 3-level wrapper
 * (chapter→section→KP, all same name) only because KPs require a
 * Section/Chapter. When a chapter is just that wrapper, return its KP so
 * the tree can render it as a single row instead of three. */
export function syntheticChapterKp(
  ch: ChapterNode,
): KnowledgePointNode | null {
  if (ch.sections.length !== 1) return null;
  const kps = ch.sections[0].knowledge_points;
  if (kps.length !== 1) return null;
  return isSyntheticKp(kps[0]) ? kps[0] : null;
}

export type ChapterTree = {
  course_id: string;
  generation_status: GenerationStatus;
  generation_error: string | null;
  chapters: ChapterNode[];
};

export class CoursesError extends Error {
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
    else if (Array.isArray(body.detail) && body.detail.length > 0) {
      const first = body.detail[0] as { msg?: string };
      if (first?.msg) detail = first.msg;
    }
  } catch {
    // ignore
  }
  throw new CoursesError(res.status, detail);
}

export async function listCourses(): Promise<Course[]> {
  return asJson<Course[]>(await fetch("/api/courses", { credentials: "include" }));
}

export async function createCourse(name: string, file: File): Promise<Course> {
  const form = new FormData();
  form.append("name", name);
  form.append("file", file);
  return asJson<Course>(
    await fetch("/api/courses", {
      method: "POST",
      credentials: "include",
      body: form,
    }),
  );
}

export async function getCourse(id: string): Promise<Course> {
  return asJson<Course>(
    await fetch(`/api/courses/${id}`, { credentials: "include" }),
  );
}

export async function deleteCourse(id: string): Promise<void> {
  const res = await fetch(`/api/courses/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok && res.status !== 204) {
    await asJson(res);
  }
}

export async function getChapterTree(courseId: string): Promise<ChapterTree> {
  return asJson<ChapterTree>(
    await fetch(`/api/courses/${courseId}/chapter-tree`, {
      credentials: "include",
    }),
  );
}
