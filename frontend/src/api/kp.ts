export type MCQOption = {
  label: string;
  text: string;
};

export type Exercise = {
  type: "mcq" | "short_answer";
  question_type: string;
  question: string;
  options?: MCQOption[];
  correct_answer: string;
};

export type KPContent = {
  kp_id: string;
  layer3_prompt: string;
  keyphrases: string[];
  exercises: Exercise[];
  difficulty: string;
  count: number;
  created_at: string;
};

export class KPError extends Error {
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
  throw new KPError(res.status, detail);
}

export async function getKPContent(
  courseId: string,
  kpId: string,
): Promise<KPContent> {
  return asJson<KPContent>(
    await fetch(`/api/courses/${courseId}/kp/${kpId}/content`, {
      credentials: "include",
    }),
  );
}

export async function postExerciseSet(
  courseId: string,
  kpId: string,
): Promise<KPContent> {
  // Body-less: difficulty + count come from the latest KPAssessment.
  return asJson<KPContent>(
    await fetch(`/api/courses/${courseId}/kp/${kpId}/exercise-set`, {
      method: "POST",
      credentials: "include",
    }),
  );
}

export type SubmissionStatus = "pending" | "running" | "done" | "failed";

export type Answer = { index: number; answer: string };

export type SubmissionMeta = {
  id: string;
  kp_id: string;
  status: SubmissionStatus;
  error: string | null;
  submitted_at: string;
  completed_at: string | null;
};

export type PerQuestionGrade = {
  index: number;
  score: number;
  feedback: string;
};

export type Grade = {
  per_question: PerQuestionGrade[];
  overall_score: number;
  overall_feedback: string;
};

export type SubmissionResult = {
  submission: SubmissionMeta;
  grade: Grade | null;
  suggestion: string | null;
};

export type AdvanceAction = "next" | "retry";

export type AdvanceResult = {
  action: AdvanceAction;
  kp_status: "untouched" | "in_progress" | "passed";
};

export async function submitAnswers(
  courseId: string,
  kpId: string,
  answers: Answer[],
): Promise<SubmissionMeta> {
  return asJson<SubmissionMeta>(
    await fetch(`/api/courses/${courseId}/kp/${kpId}/submissions`, {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ answers }),
    }),
  );
}

export async function getSubmission(
  courseId: string,
  kpId: string,
  submissionId: string,
): Promise<SubmissionResult> {
  return asJson<SubmissionResult>(
    await fetch(
      `/api/courses/${courseId}/kp/${kpId}/submissions/${submissionId}`,
      { credentials: "include" },
    ),
  );
}

export async function regradeSubmission(
  courseId: string,
  kpId: string,
  submissionId: string,
): Promise<SubmissionMeta> {
  return asJson<SubmissionMeta>(
    await fetch(
      `/api/courses/${courseId}/kp/${kpId}/submissions/${submissionId}/regrade`,
      {
        method: "POST",
        credentials: "include",
      },
    ),
  );
}

export async function advanceKP(
  courseId: string,
  kpId: string,
  action: AdvanceAction,
): Promise<AdvanceResult> {
  return asJson<AdvanceResult>(
    await fetch(`/api/courses/${courseId}/kp/${kpId}/advance`, {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action }),
    }),
  );
}
