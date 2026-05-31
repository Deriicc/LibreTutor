"""Real-API deep test: 出题 → 判题 only. No mocks.

Runs the live exercise-set generator + grader against several subjects
(simulating diverse real users) and two student profiles per set:

  A. paraphrased-correct  — right idea, wording != reference  (probes #3)
  B. off-topic / wrong    — short answers answer the wrong thing (probes #3)

Per run it audits the three reported defects:
  #1 text-referential stems  (「根据文本/文中/作者…」 — student never read it)
  #2 short_answer carries explicit grading_criteria
  #3 fairness: A's short answers score high, B's score low

Creds come from backend/.env (CHAT_*). Costs real tokens. Run:
  cd backend && .venv/bin/python -m scripts.deeptest_exercise_grading
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path

import json

import fitz  # type: ignore[import-untyped]

from app.config import settings
from app.kp import grader
from app.kp.exercise_validators import _TEXT_REFERENTIAL
from app.kp.materializer import generate_exercise_set
from app.llm import complete_json

API = {
    "chat_api_key": settings.chat_api_key,
    "chat_base_url": settings.chat_base_url,
    "chat_model": settings.chat_model,
}

# (title, keyphrases, page text, count, difficulty)
SCENARIOS = [
    (
        "勾股定理",
        ["勾股定理", "直角三角形", "斜边"],
        "勾股定理：直角三角形两条直角边的平方和等于斜边的平方，"
        "即 a^2 + b^2 = c^2，其中 c 为斜边。常用于求未知边长、判定"
        "直角三角形，以及在坐标系中计算两点间距离。",
        5,
        "normal",
    ),
    (
        "光合作用",
        ["光合作用", "叶绿体", "二氧化碳"],
        "光合作用是绿色植物在叶绿体中利用光能，把二氧化碳和水"
        "转化为有机物（葡萄糖）并释放氧气的过程。分光反应与暗反应"
        "两阶段，光反应在类囊体膜上进行并产生 ATP 与 NADPH。",
        4,
        "easy",
    ),
    (
        "法国大革命",
        ["法国大革命", "三级会议", "人权宣言"],
        "1789 年法国大革命爆发，三级会议召开后第三等级成立国民"
        "议会，攻占巴士底狱成为革命象征，随后通过《人权宣言》，"
        "宣告自由平等与主权在民，深刻冲击了欧洲旧君主制度。",
        5,
        "normal",
    ),
]


def _make_pdf(text: str) -> str:
    path = Path(tempfile.mkdtemp()) / "src.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(50, 50, 545, 780), text, fontsize=12)
    doc.save(path)
    doc.close()
    return str(path)


async def _simulate_good_short_answers(exercises: list) -> dict[int, str]:
    """Profile A = a competent real student: answers each short-answer
    CORRECTLY but in plain, natural language — explicitly told NOT to copy
    textbook/reference phrasing. This is the genuine probe for defect #3
    (right idea, different wording must still score well)."""
    shorts = [(i, e.question) for i, e in enumerate(exercises)
              if e.type == "short_answer"]
    if not shorts:
        return {}
    qlist = "\n".join(f"[{i}] {q}" for i, q in shorts)
    msg = [
        {"role": "system", "content":
         "你是一名学得不错、但用自己口语化表达的学生。请正确回答每道题，"
         "答案要点要对、推理要在，但**刻意不要照搬教材或标准答案的措辞**，"
         "用自己的话说，2-4 句。仅输出 JSON："
         '{"answers":[{"index":int,"answer":"中文作答"}]}'},
        {"role": "user", "content": qlist},
    ]
    raw = await complete_json(API, msg)
    data = json.loads(raw)
    out: dict[int, str] = {}
    for item in data.get("answers", []):
        out[int(item["index"])] = str(item["answer"])
    return out


async def _student_answers(exercises: list, profile: str) -> dict[int, str]:
    """profile A = LLM-simulated competent student (correct, own words);
    B = off-topic/wrong (clear negative control)."""
    ans: dict[int, str] = {}
    good_short = (
        await _simulate_good_short_answers(exercises) if profile == "A" else {}
    )
    for i, ex in enumerate(exercises):
        if ex.type == "mcq":
            opts = [o.label for o in (ex.options or [])]
            if profile == "A":
                ans[i] = ex.correct_answer
            else:
                wrong = [o for o in opts if o != ex.correct_answer]
                ans[i] = wrong[0] if wrong else opts[0]
        else:
            if profile == "A":
                ans[i] = good_short.get(i, "（模拟作答缺失）")
            else:
                ans[i] = "我觉得这跟昨天吃的火锅味道有关系，应该是辣度的问题。"
    return ans


def _audit_generation(title: str, exercises: list) -> list[str]:
    findings: list[str] = []
    for i, e in enumerate(exercises):
        m = _TEXT_REFERENTIAL.search(e.question)
        if m:
            findings.append(
                f"#1 第{i+1}题 命中文本指向 {m.group(0)!r}: {e.question[:50]!r}"
            )
        if e.type == "short_answer":
            gc = e.grading_criteria
            if not gc or not (1 <= len(gc) <= 5) or not all(
                c and c.strip() for c in gc
            ):
                findings.append(f"#2 第{i+1}题 grading_criteria 不合规: {gc!r}")
    return findings


async def _grade_async(exercises_json, answers):
    llm = await grader._call_llm_grade(exercises_json, answers, API)
    pq = grader._override_mcq_scores(exercises_json, answers, llm.per_question)
    return pq, llm.overall_feedback


async def run_scenario(title, keyphrases, text, count, difficulty):
    print(f"\n{'='*70}\n[{title}] count={count} difficulty={difficulty}")
    pdf = _make_pdf(text)
    try:
        payload = await generate_exercise_set(
            title, pdf, 1, 1,
            keyphrases=keyphrases,
            covered_concepts=None,
            difficulty=difficulty,
            count=count,
            api_settings=API,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  GENERATION RAISED (retries exhausted): {exc}")
        return {"title": title, "gen_failed": str(exc)}

    exercises = payload.exercises
    gen_findings = _audit_generation(title, exercises)
    ex_json = [e.model_dump(mode="json") for e in exercises]

    for i, e in enumerate(exercises):
        tag = e.type
        print(f"  Q{i+1} [{tag}/{e.question_type}] {e.question[:60]}")
        if e.type == "short_answer":
            print(f"     评分要点: {e.grading_criteria}")

    result = {"title": title, "gen_findings": gen_findings, "fairness": []}
    for profile in ("A", "B"):
        ans = await _student_answers(exercises, profile)
        pq, overall = await _grade_async(ex_json, ans)
        short_scores = [
            pq[i]["score"] for i, e in enumerate(exercises)
            if e.type == "short_answer"
        ]
        avg = sum(short_scores) / len(short_scores) if short_scores else 0
        label = "paraphrased-correct" if profile == "A" else "off-topic/wrong"
        print(f"  profile {profile} ({label}) short scores={short_scores} "
              f"avg={avg:.0f}")
        for i, e in enumerate(exercises):
            if e.type == "short_answer":
                print(f"     Q{i+1} score={pq[i]['score']}")
                print(f"        ans={ans[i][:90]}")
                print(f"        fb={pq[i]['feedback'][:90]}")
        result["fairness"].append((profile, avg, short_scores))

    # #3 verdict: A should be clearly > B and A not punished for wording
    a = next(f for f in result["fairness"] if f[0] == "A")
    b = next(f for f in result["fairness"] if f[0] == "B")
    if a[1] < 60:
        gen_findings.append(
            f"#3 UNFAIR: paraphrased-correct avg={a[1]:.0f} (<60) — "
            f"penalized for not matching reference wording"
        )
    if b[1] >= 60:
        gen_findings.append(
            f"#3 LENIENT: off-topic avg={b[1]:.0f} (>=60) — wrong answers credited"
        )
    if a[1] < b[1] + 20:
        gen_findings.append(
            f"#3 WEAK SEPARATION: A({a[1]:.0f}) vs B({b[1]:.0f}) gap < 20"
        )
    return result


async def main():
    if not API["chat_api_key"]:
        raise SystemExit("CHAT_API_KEY empty in backend/.env")
    all_findings: list[str] = []
    for sc in SCENARIOS:
        r = await run_scenario(*sc)
        if r.get("gen_failed"):
            all_findings.append(f"[{r['title']}] GEN FAILED: {r['gen_failed']}")
        for f in r.get("gen_findings", []):
            all_findings.append(f"[{r['title']}] {f}")

    print(f"\n{'='*70}\nSUMMARY")
    if not all_findings:
        print("  No defect signals across scenarios — fixes hold under real API.")
    else:
        for f in all_findings:
            print(f"  ✗ {f}")


if __name__ == "__main__":
    asyncio.run(main())
