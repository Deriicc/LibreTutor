"""End-to-end deep test: simulate a 30-round student dialogue, then exercise
the assessment + exercise generation pipeline against a real LLM.

What this script tests:
1. Layer 1 four-stage prompt: does the LLM actually anchor at some point?
   (we look for transition phrases like "也就是说", "换句话说", "我直接告诉你")
2. Assessment quality: covered/partial/untouched correctly map to what the
   student demonstrated?
3. Exercise hard-constraint: do the generated questions stay within the
   covered_concepts whitelist?
4. Difficulty mapping: does the suggested difficulty drive the right
   question types?

Run from backend/:
    python scripts/deep_test_assessment.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

# Make sure backend/ is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env so DEEPSEEK_API_KEY etc. are populated.
ENV_PATH = Path(__file__).parent.parent / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from app.chat.socratic import build_system_prompt, count_turns
from app.db import SessionLocal
from app.kp.materializer import generate_exercise_set
from app.llm import stream_chat
from app.models import (
    Chapter,
    Course,
    GenerationStatus,
    KnowledgePoint,
    KPMaterial,
    Message,
    MessageRole,
    Section,
    User,
)


# --------- Test KP setup ---------

KP_TITLE = "导数"
KNOWLEDGE_CHECKLIST = [
    {
        "concept": "导数定义",
        "description": "导数是函数在某一点的瞬时变化率，定义为极限 f'(x) = lim_{h→0} (f(x+h)-f(x))/h",
        "must_anchor": True,
    },
    {
        "concept": "切线斜率",
        "description": "导数的几何意义是函数图像在该点切线的斜率",
        "must_anchor": True,
    },
    {
        "concept": "可导与连续",
        "description": "可导一定连续，但连续不一定可导（如尖点处）",
        "must_anchor": False,
    },
    {
        "concept": "导数的物理意义",
        "description": "导数表示瞬时速度、瞬时变化率等物理量",
        "must_anchor": False,
    },
]

# 30 rounds of student utterances. Modeling a "medium-engaged" student:
# - Rounds 1-5: vague guesses, mostly wrong
# - Rounds 6-10: gets some basics, starts asking questions
# - Rounds 11-20: deeper engagement, occasional confusion
# - Rounds 21-30: applies the concept, makes connections
STUDENT_SCRIPT = [
    # 1-5: vague start
    "嗯……导数是不是函数下降的速度？",
    "我记得高中学过，但忘了具体公式",
    "是不是斜率？",
    "不太懂极限怎么定义导数",
    "老师能不能直接讲？我有点跟不上",
    # 6-10: starting to engage
    "哦，瞬时变化率的意思是某一刻的变化速度对吗？",
    "那匀速运动的导数就是常数咯？",
    "如果是 y = x^2，那 y' 是什么？",
    "怎么算 lim_{h→0} ((x+h)^2 - x^2)/h ?",
    "啊我懂了，展开后 (2xh + h^2)/h = 2x + h，h→0 就是 2x",
    # 11-20: deeper engagement
    "那 y = x^3 的导数是 3x^2 吗？",
    "为什么 |x| 在 0 处导数不存在？",
    "左右导数是什么意思？",
    "原来 |x| 在 0 处左导数是 -1，右导数是 +1，所以不可导",
    "那连续是不是也保证不了可导？",
    "可导的话一定连续吗？",
    "让我想想……如果 f 在 a 处可导，那 f(a+h)-f(a) = f'(a)·h + o(h)，h→0 时 f(a+h)→f(a)，所以连续",
    "那如果导数在某点处突然变了，会怎样？",
    "导数的物理意义是不是就是瞬时速度？",
    "对，加速度也是位移对时间的二阶导数",
    # 21-30: applying & connecting
    "那如果一辆车的位置 s(t) = 5t^2 + 3t，t=2 时的瞬时速度是？",
    "s'(t) = 10t + 3，所以 s'(2) = 23",
    "导数在生活中还有什么用？",
    "经济学里边际成本是不是就是成本对产量的导数？",
    "原来如此！那 GDP 增长率是不是 GDP 函数对时间的导数除以 GDP？",
    "hmm 这个相对增长率的概念有点烧脑",
    "切线斜率的几何含义在二维图像里很直观，三维呢？",
    "三维曲面的话需要偏导吧？",
    "好的我大概理解了。最后问一个：可导但导函数不连续的例子有吗？",
    "感觉懂了！可以做题去试试了",
]

assert len(STUDENT_SCRIPT) == 30


# --------- Utility ---------


async def _setup_kp() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create a fresh course/KP with the test checklist. Cleans up any
    prior 'deep_test' user before re-running."""
    suffix = uuid.uuid4().hex[:6]
    async with SessionLocal() as db:
        user = User(username=f"deep_test_{suffix}", password_hash="x")
        db.add(user)
        await db.flush()

        course = Course(
            user_id=user.id,
            name="深度测试",
            source_pdf_path="/tmp/_deep_test.pdf",
            generation_status=GenerationStatus.done,
        )
        db.add(course)
        await db.flush()

        chapter = Chapter(course_id=course.id, title="微积分基础", order_index=0)
        db.add(chapter)
        await db.flush()

        section = Section(chapter_id=chapter.id, title="导数与微分", order_index=0)
        db.add(section)
        await db.flush()

        kp = KnowledgePoint(
            section_id=section.id,
            title=KP_TITLE,
            order_index=0,
            boundary={"page_start": 1, "page_end": 3},
        )
        db.add(kp)
        await db.flush()

        db.add(
            KPMaterial(
                kp_id=kp.id,
                layer3_prompt="先从直观的瞬时变化率切入，再过渡到极限的精确定义。注意区分可导与连续。",
                keyphrases=["导数", "极限", "切线斜率", "可导", "连续"],
                knowledge_checklist=KNOWLEDGE_CHECKLIST,
            )
        )

        await db.commit()
        return user.id, course.id, kp.id


def _short(s: str, n: int = 80) -> str:
    s = s.strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 3] + "..."


# --------- Driver ---------


async def run_30_round_dialogue(course_id: uuid.UUID, kp_id: uuid.UUID) -> None:
    """For each student utterance: build system prompt, call LLM as teacher,
    persist both messages."""
    print("=" * 80)
    print("阶段 1：30 轮对话")
    print("=" * 80)

    # Track anchoring transitions
    anchor_phrases = ["也就是说", "换句话说", "我直接告诉你", "准确的说法", "定义如下"]
    anchor_rounds: list[int] = []

    for round_idx, student_msg in enumerate(STUDENT_SCRIPT, start=1):
        # Persist student message
        async with SessionLocal() as db:
            db.add(
                Message(kp_id=kp_id, role=MessageRole.user, content=student_msg)
            )
            await db.commit()

        # Build system prompt + history, call teacher LLM
        async with SessionLocal() as db:
            from sqlalchemy import select

            history_q = await db.execute(
                select(Message)
                .where(Message.kp_id == kp_id)
                .order_by(Message.created_at)
            )
            history = list(history_q.scalars().all())
            turn_count = count_turns(history)

            system_content = await build_system_prompt(
                course_id, kp_id, KP_TITLE, db, turn_count=turn_count
            )

        llm_messages = [{"role": "system", "content": system_content}]
        llm_messages.extend(
            {"role": m.role.value, "content": m.content} for m in history
        )

        # Stream the LLM response
        teacher_reply_parts: list[str] = []
        try:
            async for delta in stream_chat(llm_messages, temperature=0.8):
                teacher_reply_parts.append(delta)
        except Exception as exc:
            print(f"[Round {round_idx}] LLM error: {exc}")
            return

        teacher_reply = "".join(teacher_reply_parts)
        if not teacher_reply.strip():
            print(f"[Round {round_idx}] empty LLM reply, aborting")
            return

        # Persist teacher reply
        async with SessionLocal() as db:
            db.add(
                Message(
                    kp_id=kp_id,
                    role=MessageRole.assistant,
                    content=teacher_reply,
                )
            )
            await db.commit()

        # Detect anchoring
        if any(p in teacher_reply for p in anchor_phrases):
            anchor_rounds.append(round_idx)
            marker = "🎯锚定"
        else:
            marker = "  "

        print(
            f"[R{round_idx:>2}] {marker} 学:{_short(student_msg, 50):<50} "
            f"师:{_short(teacher_reply, 80)}"
        )

    print()
    print(f"锚定轮次：{anchor_rounds} (共 {len(anchor_rounds)} 次)")
    if not anchor_rounds:
        print("⚠️ 警告：30 轮内未检测到锚定过渡句。Layer 1 prompt 可能未生效。")
    print()


async def run_assessment_and_analyze(kp_id: uuid.UUID) -> dict:
    """Run the assessor LLM, print + return its output. Captures the raw
    LLM response so we can diagnose strict-validation failures."""
    print("=" * 80)
    print("阶段 2：评估")
    print("=" * 80)

    # Bypass the assessor's strict validation here; we want to see the raw
    # LLM output and decide whether the failure is "LLM ignored prompt" or
    # "checklist drift we can tolerate".
    from app.kp import assessor as assessor_module
    from app.models import Message
    from sqlalchemy import select

    async with SessionLocal() as db:
        kp = await db.get(KnowledgePoint, kp_id)
        material = await db.get(KPMaterial, kp_id)
        history_q = await db.execute(
            select(Message).where(Message.kp_id == kp_id).order_by(Message.created_at)
        )
        history = list(history_q.scalars().all())

    messages = assessor_module.build_assessment_messages(
        kp_title=kp.title,
        checklist_block=assessor_module.render_checklist_for_assessor(
            material.knowledge_checklist
        ),
        history_block=assessor_module.render_history_block(history),
    )

    raw = await assessor_module.complete_json(messages)
    print("LLM 原始响应（截断 1500 字符）：")
    print(raw[:1500])
    print("...\n" if len(raw) > 1500 else "")

    expected_concepts = [item["concept"] for item in material.knowledge_checklist]
    print(f"期望的概念集合: {expected_concepts}\n")

    try:
        payload = assessor_module.parse_and_validate_payload(
            raw, expected_concepts=expected_concepts
        )
        print("✓ 严格校验通过\n")
        valid = True
    except ValueError as exc:
        print(f"✗ 严格校验失败: {exc}\n")
        # Soft-parse: just JSON-decode without enforcing concept set
        data = json.loads(raw)
        valid = False
        # Diagnose concept drift
        actual_concepts = set()
        for bucket in ("covered", "partial", "untouched"):
            for item in data.get(bucket, []):
                actual_concepts.add(item.get("concept", ""))
        expected_set = set(expected_concepts)
        missing = expected_set - actual_concepts
        extra = actual_concepts - expected_set
        if missing:
            print(f"  漏掉: {sorted(missing)}")
        if extra:
            print(f"  多出: {sorted(extra)}")
        # Print near-matches
        for m in missing:
            for a in actual_concepts:
                if m in a or a in m:
                    print(f"  💡 近似匹配: 期望 '{m}' ↔ LLM 返回 '{a}'")

        # Build a payload anyway by mapping near-matches
        return {
            "covered": data.get("covered", []),
            "partial": data.get("partial", []),
            "untouched": data.get("untouched", []),
            "coverage_ratio": data.get("coverage_ratio", 0.0),
            "mastery_summary": data.get("mastery_summary", ""),
            "suggested_difficulty": data.get("suggested_difficulty", "normal"),
            "suggested_count": data.get("suggested_count", 5),
            "_validation_failed": True,
        }

    out = {
        "covered": [c.model_dump() for c in payload.covered],
        "partial": [p.model_dump() for p in payload.partial],
        "untouched": [u.model_dump() for u in payload.untouched],
        "coverage_ratio": payload.coverage_ratio,
        "mastery_summary": payload.mastery_summary,
        "suggested_difficulty": payload.suggested_difficulty,
        "suggested_count": payload.suggested_count,
    }

    print(f"覆盖度：{out['coverage_ratio']:.0%}")
    print(f"建议难度：{out['suggested_difficulty']}")
    print(f"建议题量：{out['suggested_count']} 题")
    print(f"\n概要：{out['mastery_summary']}\n")

    print(f"已掌握 ({len(out['covered'])}):")
    for c in out["covered"]:
        print(f"  ✓ {c['concept']}: {_short(c.get('evidence', ''), 100)}")
    print(f"\n部分掌握 ({len(out['partial'])}):")
    for p in out["partial"]:
        print(f"  ~ {p['concept']}: {_short(p.get('evidence', ''), 100)}")
    print(f"\n未触及 ({len(out['untouched'])}):")
    for u in out["untouched"]:
        print(f"  — {u['concept']}: {_short(u.get('reason', ''), 100)}")
    print()

    return out


async def run_exercise_generation(
    kp_id: uuid.UUID, assessment: dict, pdf_path: str
) -> None:
    """Generate exercises with the suggested params + the covered+partial
    whitelist (merged with keyphrases as semantic equivalents). Verify
    hard constraints."""
    print("=" * 80)
    print("阶段 3：作业生成（用评估建议的参数）")
    print("=" * 80)

    covered_concepts = [c["concept"] for c in assessment["covered"]] + [
        p["concept"] for p in assessment["partial"]
    ]

    # Merge in keyphrases — this matches what materialize_kp_exercise_set
    # does internally in production.
    async with SessionLocal() as db:
        material = await db.get(KPMaterial, kp_id)
        keyphrases = list(material.keyphrases or []) if material else []
    covered_concepts.extend(keyphrases)
    seen: set[str] = set()
    covered_concepts = [
        c for c in covered_concepts if not (c in seen or seen.add(c))
    ]

    difficulty = assessment["suggested_difficulty"]
    count = assessment["suggested_count"]

    print(f"参数：difficulty={difficulty}, count={count}")
    print(f"考察范围（含 keyphrases）：{covered_concepts}")
    print()

    # Need a real PDF for extract_kp_text. Make one quickly.
    import fitz  # type: ignore[import-untyped]

    doc = fitz.open()
    pdf_text = (
        "导数是函数在某一点的瞬时变化率。设 f(x) 在点 x_0 处可导，"
        "则 f'(x_0) = lim_{h→0} (f(x_0+h) - f(x_0)) / h。"
        "几何上，导数等于函数图像在该点切线的斜率。"
        "如果 f 在 x_0 可导，那么 f 在 x_0 连续；反之不一定，例如 |x| 在 0 处连续但不可导。"
        "导数在物理上代表瞬时速度，例如位置 s(t) 关于时间的导数 s'(t) 就是瞬时速度。"
    )
    page = doc.new_page()
    page.insert_text((50, 72), pdf_text)
    doc.save(pdf_path)
    doc.close()

    try:
        result = await generate_exercise_set(
            kp_title=KP_TITLE,
            pdf_path=pdf_path,
            page_start=1,
            page_end=1,
            keyphrases=keyphrases,
            covered_concepts=covered_concepts if covered_concepts else None,
            difficulty=difficulty,
            count=count,
        )
    except Exception as exc:
        print(f"❌ 作业生成失败：{exc}")
        return

    print(f"生成 {len(result.exercises)} 道题：")
    for i, e in enumerate(result.exercises, 1):
        print(f"  {i}. [{e.type}/{e.question_type}] {_short(e.question, 100)}")
    print()

    # Hard-constraint check: every question must contain at least one covered concept
    if covered_concepts:
        print("约束验证：")
        all_pass = True
        for i, e in enumerate(result.exercises, 1):
            in_scope = [c for c in covered_concepts if c in e.question]
            if not in_scope:
                print(f"  ❌ Q{i} 题干不含任何已讨论概念: {_short(e.question, 80)}")
                all_pass = False
            else:
                print(f"  ✓ Q{i} 命中: {in_scope}")
        if all_pass:
            print("  → 全部 {} 道题都在考察范围内 ✓".format(len(result.exercises)))
    print()


async def main():
    print()
    print("╭" + "─" * 78 + "╮")
    print("│" + "深度端到端测试：30 轮对话 → 评估 → 作业".center(74) + "│")
    print("╰" + "─" * 78 + "╯")
    print()

    # --reuse-kp <uuid> skips the 30-round dialogue and re-uses an existing
    # KP's history (saves ~3min and ~1k LLM tokens during iteration).
    reuse_kp_id: uuid.UUID | None = None
    for i, arg in enumerate(sys.argv):
        if arg == "--reuse-kp" and i + 1 < len(sys.argv):
            reuse_kp_id = uuid.UUID(sys.argv[i + 1])
            break

    if reuse_kp_id is not None:
        async with SessionLocal() as db:
            kp = await db.get(KnowledgePoint, reuse_kp_id)
            assert kp is not None, f"KP {reuse_kp_id} not found"
            section = await db.get(Section, kp.section_id)
            chapter = await db.get(Chapter, section.chapter_id)
            course_id = chapter.course_id
        kp_id = reuse_kp_id
        print(f"复用已有 KP：{kp_id}\n")
        print("跳过 30 轮对话，直接进入评估阶段。\n")
    else:
        _, course_id, kp_id = await _setup_kp()
        print(f"测试 KP id: {kp_id}\n")
        await run_30_round_dialogue(course_id, kp_id)

    assessment = await run_assessment_and_analyze(kp_id)

    pdf_path = f"/tmp/_deep_test_{uuid.uuid4().hex[:6]}.pdf"
    await run_exercise_generation(kp_id, assessment, pdf_path)

    print("=" * 80)
    print("测试完成")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
