export type DiaryEntryStatus = "pending" | "running" | "done" | "failed";

export type DiaryEntry = {
  kp_id: string;
  kp_title: string;
  attempt: number;
  body: string | null;
  author_signature: string | null;
  author_label: string | null;
  status: DiaryEntryStatus;
  created_at: string | null;
};

export type CourseDiary = {
  course_name: string;
  entries: DiaryEntry[];
};

export class DiaryError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function getCourseDiary(
  courseId: string,
): Promise<CourseDiary> {
  const res = await fetch(`/api/courses/${courseId}/diary`, {
    credentials: "include",
  });
  if (!res.ok) {
    throw new DiaryError(res.status, `加载日记失败 (HTTP ${res.status})`);
  }
  return (await res.json()) as CourseDiary;
}
