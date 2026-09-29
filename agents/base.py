"""What every instrument agent shares: prompt building, the validator retry loop,
the optional check_my_part tool (phase 7a), bar-limited revisions (phase 6) and
feedback to the composer (phase 7c).
"""

import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from core.config import Settings
from core.describe import describe_blueprint, describe_part, describe_parts
from core.json_schemas import PART, PART_WITH_FEEDBACK
from core.llm import LLMOutputError
from core.theory import FLAT_NAMES, SHARP_NAMES, key_pitch_classes, note_name, uses_flats
from core.timeline import bar_map, beats_per_bar, total_bars
from core.validator import PITCH_RANGES, normalize_part, repair_part, validate_part

Log = Callable[[str], None]

COMMON_RULES = """\
You are one musician in a band of AI agents. A composer wrote a blueprint (key, tempo,
sections, one chord per bar, which instruments play in each section). You write ONLY your
own part, as JSON: {"notes": [{"pitch", "start_beat", "duration", "velocity"}, ...]}.

Timing rules:
- A beat is a quarter note. start_beat is counted from 0 at the very start of the song.
  Bar N (1-based) starts at start_beat (N - 1) * beats_per_bar.
- duration is in beats. velocity is 1-127 (45-65 soft, 70-95 normal, 100-120 accents).
- Play only in bars where the bar map lists your instrument. Nothing may ring past the end.

Pitch rules (a validator checks these and sends violations back to you):
- Stay inside your pitch range and use only notes of the key (listed in the request).
- Follow the chord of each bar; put chord tones on strong beats.

Musicianship:
- Serve the song. Match each section's energy: sparse and soft when low, fuller and
  louder when high. Contrast between sections makes a song feel composed.
- Listen to the parts already written (shown in the request) and fit with them.
- Leave space. Repetition with small variations beats constant novelty.
"""


@dataclass
class PartResult:
    notes: List[dict]
    attempts: int
    repaired: List[str] = field(default_factory=list)  # fixes code made after retries ran out
    feedback: str = ""


class AgentFailed(RuntimeError):
    pass


def key_notes_text(bp: dict) -> str:
    names = FLAT_NAMES if uses_flats(bp["key"], bp["mode"]) else SHARP_NAMES
    pcs = key_pitch_classes(bp["key"], bp["mode"])
    root = names.index(bp["key"]) if bp["key"] in names else 0
    ordered = [names[(root + i) % 12] for i in range(12) if (root + i) % 12 in pcs]
    return f"{bp['key']} {bp['mode']}: {' '.join(ordered)} (every other note is rejected)"


def splice(current: List[dict], new: List[dict], bars: List[int], bp: dict) -> List[dict]:
    """Replace the notes that start in `bars` with `new`."""
    bpb = beats_per_bar(bp)
    keep = [n for n in current if int(n["start_beat"] // bpb) + 1 not in bars]
    return sorted(keep + new, key=lambda n: (n["start_beat"], n["pitch"]))


class InstrumentAgent:
    def __init__(self, role: str, guidance: str):
        self.role = role
        self.system_prompt = COMMON_RULES + "\n" + guidance

    # ------------------------------------------------------------------ prompts

    def request(self, bp: dict, parts: Dict[str, List[dict]], task: str) -> str:
        lo, hi = PITCH_RANGES[self.role]
        heard = {r: n for r, n in parts.items() if r != self.role}
        return "\n\n".join([
            describe_blueprint(bp),
            f"Your instrument: {self.role}. Pitch range: {lo}-{hi} ({note_name(lo)}-{note_name(hi)})."
            + ("" if self.role == "drums" else f"\nNotes in the key: {key_notes_text(bp)}"),
            "Parts already written (bar: note@beat-in-bar(duration beats)):\n" + describe_parts(heard, bp),
            "TASK: " + task,
        ])

    # ------------------------------------------------------------------ public

    def write(self, llm, settings: Settings, bp: dict, parts: Dict[str, List[dict]],
              log: Log = print) -> PartResult:
        n = total_bars(bp)
        playing = [b["bar"] for b in bar_map(bp) if self.role in b["roles"]]
        task = (f"Write the {self.role} part for the whole song ({n} bars). Play in bars "
                f"{_ranges(playing)} and stay silent elsewhere.")
        return self._run(llm, settings, bp, parts, task, context={"blueprint": bp, "parts": parts},
                         finish=lambda notes: notes, log=log)

    def revise(self, llm, settings: Settings, bp: dict, parts: Dict[str, List[dict]],
               issue: dict, revision: int, log: Log = print) -> PartResult:
        """Rewrite only the bars the critic flagged."""
        first, last = issue["first_bar"], issue["last_bar"]
        bars = list(range(first, last + 1))
        current = parts[self.role]
        bpb = beats_per_bar(bp)
        task = (f"The critic flagged bars {first}-{last} of your {self.role} part.\n"
                f"Problem: {issue['problem']}\nSuggested fix: {issue.get('fix', '')}\n"
                f"Your current notes in those bars:\n{describe_part(self.role, current, bp, bars)}\n"
                f"Rewrite ONLY bars {first}-{last}: return just the notes that start in those bars "
                f"(start_beat from {(first - 1) * bpb} up to, not including, {last * bpb}). "
                f"Everything else in your part stays as it is.")

        def only_flagged(notes):
            return [n for n in notes if first <= int(n.get("start_beat", -1) // bpb) + 1 <= last]

        return self._run(llm, settings, bp, parts, task,
                         context={"blueprint": bp, "parts": parts, "bars": bars, "revision": revision},
                         finish=lambda notes: splice(current, only_flagged(notes), bars, bp), log=log)

    # ------------------------------------------------------------------ the loop

    def _run(self, llm, settings: Settings, bp: dict, parts: Dict[str, List[dict]], task: str,
             context: dict, finish: Callable[[List[dict]], List[dict]], log: Log) -> PartResult:
        schema_name, schema = ("part_with_feedback", PART_WITH_FEEDBACK) if settings.feedback \
            else ("part", PART)
        if settings.feedback:
            task += ("\nIf something in the blueprint makes your job hard (tempo, chords, "
                     "sections, register), say so in feedback_to_composer; otherwise leave it ''.")
        messages = [{"role": "user", "content": self.request(bp, parts, task)}]
        tools = self._tools(bp, finish) if settings.self_check else None

        best: Optional[List[dict]] = None
        best_errors = None
        feedback = ""
        for attempt in range(1, settings.max_retries + 2):
            try:
                out = llm.generate(agent=self.role, system=self.system_prompt, messages=messages,
                                   schema_name=schema_name, schema=schema, context=context, tools=tools)
                notes = finish(normalize_part(self.role, out.get("notes", []), bp))
                errors = validate_part(self.role, notes, bp)
                feedback = out.get("feedback_to_composer", "") or feedback
                answer = json.dumps(out)
            except LLMOutputError as e:
                notes, errors, answer = None, [str(e)], e.raw or "(no usable answer)"
            if not errors:
                log(f"  {self.role}: ok ({len(notes)} notes, attempt {attempt})")
                return PartResult(notes, attempt, feedback=feedback)
            log(f"  {self.role}: attempt {attempt} rejected - {len(errors)} problem(s), e.g. {errors[0]}")
            if notes is not None and (best_errors is None or len(errors) < len(best_errors)):
                best, best_errors = notes, errors
            messages += [
                {"role": "assistant", "content": answer},
                {"role": "user", "content": "The validator rejected that part:\n- "
                 + "\n- ".join(errors[:25]) + "\nFix exactly these problems and send the complete "
                 "JSON again."},
            ]
        if best is None:
            raise AgentFailed(f"{self.role}: no usable part after {settings.max_retries + 1} attempts")
        repaired, fixes = repair_part(self.role, best, bp)
        repaired = finish(repaired)  # preserve unflagged bars even during fallback repair
        remaining = validate_part(self.role, repaired, bp)
        if remaining:
            raise AgentFailed(f"{self.role}: still invalid after repair: {remaining[:3]}")
        log(f"  {self.role}: retries used up; code repaired it ({len(fixes)} fix(es))")
        return PartResult(repaired, settings.max_retries + 1, repaired=fixes, feedback=feedback)

    def _tools(self, bp: dict, finish):
        def check_my_part(args: dict) -> str:
            notes = finish(normalize_part(self.role, args.get("notes", []), bp))
            errors = validate_part(self.role, notes, bp)
            return "OK - no problems found." if not errors else "Problems:\n- " + "\n- ".join(errors[:25])

        return {"check_my_part": (
            f"Check a draft of your {self.role} part against the validator before answering. "
            "Returns 'OK' or the list of problems to fix.", PART, check_my_part)}


def _ranges(bars: List[int]) -> str:
    if not bars:
        return "(none)"
    out, start, prev = [], bars[0], bars[0]
    for b in bars[1:] + [None]:
        if b is not None and b == prev + 1:
            prev = b
            continue
        out.append(f"{start}-{prev}" if start != prev else str(start))
        if b is not None:
            start = prev = b
    return ", ".join(out)
