"""Content-language selection.

The language preference lives inside the global `api_settings` blob (the
single AppSettings row), so it already rides along to every LLM call site
that receives `api_settings` — no extra threading. "zh" (default) | "en".
"""

LANGUAGES = ("zh", "en")
DEFAULT_LANGUAGE = "zh"


def lang_of(api_settings: dict | None) -> str:
    """Return the configured content language, falling back to zh."""
    lang = (api_settings or {}).get("language")
    return lang if lang in LANGUAGES else DEFAULT_LANGUAGE
