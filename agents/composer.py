"""Composer agent: prompt -> blueprint (the shared contract), plus its version-2 jobs:
choosing which instruments play and in what order (7b) and answering the band's
feedback (7c)."""

import json
from typing import Callable, Dict, List, Optional, Tuple

from core.config import Settings
from core.describe import describe_blueprint
from core.json_schemas import ARRANGEMENT, BLUEPRINT, BLUEPRINT_REVISION
from core.llm import LLMOutputError
from core.timeline import roles_in_order, total_bars
from core.validator import validate_blueprint

Log = Callable[[str], None]

SYSTEM = """\
You are the composer and arranger of a band of AI musicians (drums, bass, chords, melody).
From a short request like "sad lo-fi, 80 BPM" you write the BLUEPRINT everyone follows.
You write no notes yourself.

Rules the validator enforces:
- key is a root (C, C#, Db, ... B) and mode is "major" or "minor".
- tempo in BPM (use the one in the request if given), time_signature [beats, 4].
- sections: each has a name, a number of bars, ONE chord per bar (len(chords) == bars),
  an energy from 0 (sparse, quiet) to 1 (full, loud), and the instruments playing in it.
- Every chord must be built only from notes of the key (diatonic), e.g. in A minor:
  Am Bdim C Dm Em F G and their 7ths (Am7, Cmaj7, Dm7, Em7, Fmaj7, G7). No borrowed or
  secondary-dominant chords.
- Chord symbols: root + one of "", m, dim, aug, 5, 7, maj7, m7, m7b5, dim7, sus2, sus4,
  6, m6, add9, madd9, 9, m9, maj9 (optionally /bass).
- instruments: the roles used anywhere in the song; programs: a General MIDI program for
  bass, chords and melody that suits the genre (e.g. lo-fi: 33 bass, 4 electric piano,
  11 vibraphone; jazz: 32 upright bass, 0 piano, 66 tenor sax).

Arranging: give the song a shape. Longer songs get an intro, verse, chorus (higher
energy, a different progression) and an outro that ends on the tonic chord. Thin out
intros and outros (not every instrument plays). Pick progressions idiomatic to the genre.
"""


def _normalize(bp: dict) -> dict:
    bp = json.loads(json.dumps(bp))  # deep copy
    if isinstance(bp.get("tempo"), float) and bp["tempo"].is_integer():
        bp["tempo"] = int(bp["tempo"])
    if isinstance(bp.get("time_signature"), list):
        bp["time_signature"] = [int(x) for x in bp["time_signature"]]
    for sec in bp.get("sections", []):
        if isinstance(sec.get("bars"), float):
            sec["bars"] = int(sec["bars"])
    return bp


def _ask(llm, settings: Settings, schema_name: str, schema: dict, request: str, context: dict,
         check: Callable[[dict], List[str]], log: Log, label: str) -> Tuple[Optional[dict], List[str]]:
    """Ask the composer, validate, send errors back, retry. Returns (answer, last errors)."""
    messages = [{"role": "user", "content": request}]
    errors: List[str] = []
    for attempt in range(1, settings.max_retries + 2):
        try:
            out = llm.generate(agent="composer", system=SYSTEM, messages=messages,
                               schema_name=schema_name, schema=schema, context=context)
            errors = check(out)
            answer = json.dumps(out)
        except LLMOutputError as e:
            out, errors, answer = None, [str(e)], e.raw or "(no usable answer)"
        if not errors:
            log(f"  composer: {label} ok (attempt {attempt})")
            return out, []
        log(f"  composer: {label} attempt {attempt} rejected - {errors[0]}")
        messages += [{"role": "assistant", "content": answer},
                     {"role": "user", "content": "The validator rejected that:\n- " + "\n- ".join(errors)
                      + "\nFix exactly these problems and send the complete JSON again."}]
    return None, errors


def compose(llm, settings: Settings, prompt: str, bars: int = 16, log: Log = print) -> dict:
    request = (f"Request: {prompt!r}\nWrite a blueprint for a song of exactly {bars} bars in total "
               f"(the sections' bars must add up to {bars}).")

    def check(out: dict) -> List[str]:
        bp = _normalize(out)
        errors = validate_blueprint(bp)
        if not errors and total_bars(bp) != bars:
            errors.append(f"sections add up to {total_bars(bp)} bars, but the song must be {bars} bars")
        out.clear()
        out.update(bp)
        return errors

    bp, errors = _ask(llm, settings, "blueprint", BLUEPRINT, request,
                      {"prompt": prompt, "bars": bars}, check, log, "blueprint")
    if bp is None:
        raise RuntimeError(f"composer could not write a valid blueprint: {errors[:3]}")
    return bp


def choose_order(llm, settings: Settings, bp: dict, log: Log = print) -> Tuple[List[str], dict]:
    """7b: the composer decides which instruments to call and in what order.
    Instruments it leaves out are removed from the blueprint."""
    request = (describe_blueprint(bp) + "\n\nYou are now the orchestrator. Decide which of the "
               "blueprint's instruments to call and in what order they write their parts. Each "
               "musician hears only the parts written before theirs, so rhythm usually comes "
               "first and the melody last. You may leave out an instrument the song doesn't need.")

    def check(out: dict) -> List[str]:
        order = out.get("order", [])
        errors = [f"{r} is not in the blueprint's instruments" for r in order if r not in bp["instruments"]]
        if not order:
            errors.append("order must name at least one instrument")
        if len(set(order)) != len(order):
            errors.append("order lists an instrument twice")
        return errors

    out, errors = _ask(llm, settings, "arrangement", ARRANGEMENT, request,
                       {"blueprint": bp}, check, log, "running order")
    if out is None:
        log(f"  composer: keeping the default order ({errors[:1]})")
        return roles_in_order(bp), bp
    order = out["order"]
    log(f"  composer: order {' -> '.join(order)} ({out.get('reason', '')})")
    if set(order) != set(bp["instruments"]):
        bp = json.loads(json.dumps(bp))
        bp["instruments"] = [r for r in bp["instruments"] if r in order]
        for sec in bp["sections"]:
            if "instruments" in sec:
                sec["instruments"] = [r for r in sec["instruments"] if r in order]
    return order, bp


def consider_feedback(llm, settings: Settings, bp: dict, feedback: Dict[str, str],
                      log: Log = print) -> Optional[dict]:
    """7c: musicians' notes come back to the composer, who may revise the blueprint.
    Returns the revised blueprint, or None to keep the current one."""
    notes = {role: text for role, text in feedback.items() if text.strip()}
    if not notes:
        return None
    request = (describe_blueprint(bp) + "\n\nFeedback from the band:\n"
               + "\n".join(f"- {role}: {text}" for role, text in notes.items())
               + f"\n\nRevise the blueprint only if the feedback points at a real problem. Keep the "
               f"song {total_bars(bp)} bars long. Return revise=false and the unchanged blueprint "
               f"otherwise.")

    def check(out: dict) -> List[str]:
        if not out.get("revise"):
            return []
        new = _normalize(out.get("blueprint", {}))
        errors = validate_blueprint(new)
        if not errors and total_bars(new) != total_bars(bp):
            errors.append(f"the revised song has {total_bars(new)} bars; keep {total_bars(bp)}")
        out["blueprint"] = new
        return errors

    out, errors = _ask(llm, settings, "blueprint_revision", BLUEPRINT_REVISION, request,
                       {"blueprint": bp, "feedback": notes}, check, log, "feedback review")
    if out is None or not out.get("revise"):
        return None
    log(f"  composer: revised the blueprint - {out.get('reason', '')}")
    return out["blueprint"]
