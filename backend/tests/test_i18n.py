"""Language selection: lang_of() + that prompt choosers return the right
variant for zh/en, and assembled prompts switch language."""
from app.chat import socratic
from app.courses import builder, teacher_persona
from app.kp import assessor, grader, materializer
from app.lang import DEFAULT_LANGUAGE, lang_of


def test_lang_of_defaults_and_validation():
    assert lang_of(None) == "zh"
    assert lang_of({}) == "zh"
    assert lang_of({"language": "en"}) == "en"
    assert lang_of({"language": "fr"}) == "zh"  # invalid → default
    assert DEFAULT_LANGUAGE == "zh"


def test_prompt_pairs_have_both_languages_and_differ():
    pairs = [
        builder.KP_SYSTEM_PROMPTS,
        builder.SKELETON_SYSTEM_PROMPTS,
        socratic.LAYER1_PROMPTS,
        assessor.ASSESSMENT_SYSTEM_PROMPTS,
        grader.GRADING_SYSTEM_PROMPTS,
        materializer.KP_MATERIAL_SYSTEM_PROMPTS,
        materializer.EXERCISE_SET_SYSTEM_PROMPTS,
        materializer.BOOK_OVERVIEW_SYSTEM_PROMPTS,
        teacher_persona.DEFAULT_SCENES,
    ]
    for p in pairs:
        assert set(p) == {"zh", "en"}
        assert p["zh"].strip() and p["en"].strip()
        assert p["zh"] != p["en"]


def test_assemble_system_prompt_switches_language():
    zh = socratic.assemble_system_prompt("L2", "L3", turn_count=0, lang="zh")
    en = socratic.assemble_system_prompt("L2", "L3", turn_count=0, lang="en")
    assert "苏格拉底" in zh
    assert "Socratic" in en and "苏格拉底" not in en


def test_assessor_messages_switch_language():
    zh = assessor.build_assessment_messages(
        kp_title="x", checklist_block="c", history_block="h", lang="zh"
    )
    en = assessor.build_assessment_messages(
        kp_title="x", checklist_block="c", history_block="h", lang="en"
    )
    assert zh[0]["content"] != en[0]["content"]
    assert "assessment" in en[0]["content"].lower()


def test_synthetic_titles_localized():
    assert builder._TITLES["en"]["overview"] == "Book Overview"
    assert builder._TITLES["zh"]["overview"] == "全书导读"
