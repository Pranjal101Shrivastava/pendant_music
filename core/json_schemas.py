"""JSON schemas the models must answer with (OpenAI structured outputs, strict mode).

Strict mode needs every property listed in "required" and additionalProperties false.
Limits like "max 3 issues" or "pitch 0-127" are enforced in code, not here.
"""

from core.theory import NOTE_TO_PC, ROLES


def _obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


NOTE = _obj({
    "pitch": {"type": "integer", "description": "MIDI pitch (60 = C4); drum-map note for drums"},
    "start_beat": {"type": "number", "description": "quarter-note beats from the song start, 0-based"},
    "duration": {"type": "number", "description": "length in beats"},
    "velocity": {"type": "integer", "description": "1-127"},
})

PART = _obj({"notes": {"type": "array", "items": NOTE}})

# 7c: a part plus an optional message for the composer
PART_WITH_FEEDBACK = _obj({
    "notes": {"type": "array", "items": NOTE},
    "feedback_to_composer": {"type": "string",
                             "description": "One or two sentences for the composer, or '' if none"},
})

SECTION = _obj({
    "name": {"type": "string"},
    "bars": {"type": "integer"},
    "chords": {"type": "array", "items": {"type": "string"}, "description": "one chord per bar"},
    "energy": {"type": "number", "description": "0 sparse/quiet .. 1 full/loud"},
    "instruments": {"type": "array", "items": {"type": "string", "enum": ROLES}},
})

BLUEPRINT = _obj({
    "title": {"type": "string"},
    "style": {"type": "string", "description": "genre and mood in a few words"},
    "key": {"type": "string", "enum": sorted(NOTE_TO_PC)},
    "mode": {"type": "string", "enum": ["major", "minor"]},
    "tempo": {"type": "number"},
    "time_signature": {"type": "array", "items": {"type": "integer"}, "description": "[beats, 4]"},
    "sections": {"type": "array", "items": SECTION},
    "instruments": {"type": "array", "items": {"type": "string", "enum": ROLES}},
    "programs": _obj({
        "bass": {"type": "integer", "description": "General MIDI program"},
        "chords": {"type": "integer", "description": "General MIDI program"},
        "melody": {"type": "integer", "description": "General MIDI program"},
    }),
})

CRITIC_REPORT = _obj({
    "verdict": {"type": "string", "enum": ["accept", "revise"]},
    "scores": _obj({
        "groove": {"type": "number", "description": "1-5"},
        "harmonic_fit": {"type": "number", "description": "1-5"},
        "variation": {"type": "number", "description": "1-5"},
        "balance": {"type": "number", "description": "1-5"},
    }),
    "summary": {"type": "string"},
    "issues": {"type": "array", "description": "at most 3, most important first", "items": _obj({
        "agent": {"type": "string", "enum": ROLES},
        "first_bar": {"type": "integer"},
        "last_bar": {"type": "integer"},
        "problem": {"type": "string"},
        "fix": {"type": "string"},
    })},
})

# 7b: the composer as orchestrator
ARRANGEMENT = _obj({
    "order": {"type": "array", "items": {"type": "string", "enum": ROLES},
              "description": "which instruments to write, in writing order"},
    "reason": {"type": "string"},
})

# 7c: the composer answering the band's feedback
BLUEPRINT_REVISION = _obj({
    "revise": {"type": "boolean"},
    "reason": {"type": "string"},
    "blueprint": BLUEPRINT,
})
