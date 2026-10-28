"""
Clarify — ask the user structured questions mid-turn (``ask_user``).

The heavy lifting (validation, routing to the active chat surface, waiting for the
answer) lives in ``utils.clarify``; this module only exposes the tool.
"""
from utils.clarify import GATEWAY, MAX_CHOICE_CHARS, MAX_CHOICES, MAX_QUESTIONS, ClarifyPolicy


def ask_user(questions=None) -> str:
    """Ask the user 1-5 questions and wait for the answers (JSON result)."""
    try:
        from config import load_config
        policy = ClarifyPolicy.from_config(load_config())
    except Exception:
        policy = ClarifyPolicy()
    return GATEWAY.ask(questions, policy=policy)


# ─── Registry ─────────────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "ask_user",
        "description": (
            "Ask the user one or more questions when you need a decision or clarification before "
            f"proceeding. Put every question in ONE call (1-{MAX_QUESTIONS} entries in `questions`; "
            "a single question is a one-entry array). Per question: single-select with up to "
            f"{MAX_CHOICES} `choices` (put your recommended option FIRST — the UI marks it "
            "'(Recommended)'), multi-select with `multi_select: true`, or open-ended by omitting "
            "`choices`. Options go ONLY in `choices`, never written inside the question text. "
            "Prefer deciding low-stakes questions yourself. The result is JSON: "
            "{responses: [{question, choices_offered, status, user_response}], outcome, notice?} where "
            "status is answered, skipped or unanswered and outcome is submitted, cancelled, timed_out "
            "or undelivered. If outcome is not submitted, do NOT ask again — proceed with a clearly "
            "stated assumption."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_QUESTIONS,
                    "description": "The questions, answered in order.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "description": "Question text, without the options"},
                            "choices": {
                                "type": "array",
                                "maxItems": MAX_CHOICES,
                                "items": {"type": "string", "maxLength": MAX_CHOICE_CHARS},
                                "description": "Options, recommended first. Omit for a free-text answer.",
                            },
                            "multi_select": {"type": "boolean", "default": False,
                                             "description": "Allow picking several choices"},
                        },
                        "required": ["question"],
                    },
                },
            },
            "required": ["questions"],
        },
    },
]

HANDLERS = {
    "ask_user": ask_user,
}
