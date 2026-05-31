// AssessmentAPI — fetches the per-attempt coverage / mastery snapshot.
// Backend wakes the LLM on each call; expect 3-5s latency.

export type CoveredItem = { concept: string; evidence: string };
export type PartialItem = { concept: string; evidence: string };
export type UntouchedItem = { concept: string; reason: string };

export type Difficulty = "easy" | "normal" | "hard";

export type Assessment = {
  kp_id: string;
  attempt: number;
  covered: CoveredItem[];
  partial: PartialItem[];
  untouched: UntouchedItem[];
  coverage_ratio: number;
  mastery_summary: string;
  suggested_difficulty: Difficulty;
  suggested_count: number;
  created_at: string;
};

export class AssessmentError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function runAssessment(
  courseId: string,
  kpId: string,
): Promise<Assessment> {
  const res = await fetch(
    `/api/courses/${courseId}/kp/${kpId}/assessment`,
    {
      method: "POST",
      credentials: "include",
    },
  );
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // ignore
    }
    throw new AssessmentError(res.status, detail);
  }
  return (await res.json()) as Assessment;
}
