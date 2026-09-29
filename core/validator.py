"""Plain-code validator (not an agent). Runs after every agent.

Every function returns a list of error strings; [] means valid. Errors name the
instrument, bar and beat so they can be sent back to the agent that made them.

normalize_part() fixes tiny timing slips before validation; repair_part() is the
last resort after an agent has used up its retries.
"""

import math
from typing import List, Tuple

from core.theory import (  # re-exported: older code and tests import these from here
    NOTE_TO_PC,
    ROLES,
    SCALE_INTERVALS,
    chord_pitch_classes,
    key_pitch_classes,
    note_name,
)
from core.timeline import bar_map, bar_of, where

# Allowed MIDI pitch range per instrument role
PITCH_RANGES = {
    "drums":  (35, 81),
    "bass":   (28, 60),
    "chords": (36, 96),
    "melody": (48, 96),
}

MONOPHONIC = {"bass", "melody"}   # one note at a time
MAX_CHORD_NOTES = 6
DRUM_GRID = 0.25                  # drums on 16ths
PITCHED_GRID = 1 / 12             # 16ths and triplets
EPS = 1e-6


def total_beats(blueprint: dict) -> float:
    beats_per_bar = blueprint["time_signature"][0]
    return sum(sec["bars"] for sec in blueprint["sections"]) * beats_per_bar


def _at(instrument: str, ev: dict, bp: dict = None) -> str:
    """'melody bar 3 beat 2.5' when a blueprint is known, else 'melody beat 10.50'."""
    if bp is not None:
        return f"{instrument} {where(bp, ev['start_beat'])}"
    return f"{instrument} beat {ev['start_beat']:.2f}"


# --------------------------------------------------------------------------- notes


def validate_note_event(ev: dict) -> List[str]:
    if not isinstance(ev, dict):
        return ["NoteEvent must be an object"]
    errors = []
    for field in ("pitch", "start_beat", "duration", "velocity"):
        if field not in ev:
            errors.append(f"NoteEvent missing field: {field}")
            continue
        value = ev[field]
        if type(value) not in (int, float) or not math.isfinite(value):
            errors.append(f"{field} must be a finite number")
        elif field in ("pitch", "velocity") and value != int(value):
            errors.append(f"{field} must be an integer")
    if errors:
        return errors
    if not 0 <= ev["pitch"] <= 127:
        errors.append(f"pitch {ev['pitch']} out of range 0-127")
    if not 1 <= ev["velocity"] <= 127:
        errors.append(f"velocity {ev['velocity']} out of range 1-127")
    if ev["duration"] <= 0:
        errors.append(f"duration must be > 0, got {ev['duration']}")
    if ev["start_beat"] < 0:
        errors.append(f"start_beat must be >= 0, got {ev['start_beat']}")
    return errors


def validate_notes_in_range(instrument: str, notes: List[dict], bp: dict = None) -> List[str]:
    if instrument not in PITCH_RANGES:
        return []
    lo, hi = PITCH_RANGES[instrument]
    return [
        f"{_at(instrument, ev, bp)}: pitch {ev['pitch']} ({note_name(ev['pitch'])}) out of range "
        f"[{lo}, {hi}] ({note_name(lo)}-{note_name(hi)})"
        for ev in notes if not (lo <= ev["pitch"] <= hi)
    ]


def validate_notes_in_key(instrument: str, notes: List[dict], key: str, mode: str,
                          bp: dict = None) -> List[str]:
    if instrument == "drums":
        return []
    pcs = key_pitch_classes(key, mode)
    return [
        f"{_at(instrument, ev, bp)}: pitch {ev['pitch']} ({note_name(ev['pitch'])}, "
        f"class {ev['pitch'] % 12}) not in {key} {mode}"
        for ev in notes if ev["pitch"] % 12 not in pcs
    ]


def validate_bar_lengths(instrument: str, notes: List[dict], song_beats: float) -> List[str]:
    return [
        f"{instrument} note ends at beat {ev['start_beat'] + ev['duration']:.2f}, "
        f"beyond song length {song_beats}"
        for ev in notes if ev["start_beat"] + ev["duration"] > song_beats + EPS
    ]


def validate_no_overlaps(instrument: str, notes: List[dict]) -> List[str]:
    """The same pitch can't start again while it is still sounding."""
    if instrument == "drums":
        return []
    errors = []
    last: dict = {}
    for ev in sorted(notes, key=lambda e: e["start_beat"]):
        p = ev["pitch"]
        if p in last:
            prev_end = last[p]["start_beat"] + last[p]["duration"]
            if ev["start_beat"] < prev_end - EPS:
                errors.append(
                    f"{instrument} pitch {p} overlaps at beat {ev['start_beat']:.2f}"
                )
        last[p] = ev
    return errors


def validate_monophonic(instrument: str, notes: List[dict], bp: dict = None) -> List[str]:
    """Bass and melody play one note at a time."""
    if instrument not in MONOPHONIC:
        return []
    errors = []
    ordered = sorted(notes, key=lambda e: e["start_beat"])
    for prev, ev in zip(ordered, ordered[1:]):
        if ev["start_beat"] < prev["start_beat"] + prev["duration"] - EPS:
            errors.append(
                f"{_at(instrument, ev, bp)}: {note_name(ev['pitch'])} starts while "
                f"{note_name(prev['pitch'])} is still sounding - {instrument} plays one note "
                f"at a time, shorten the earlier note"
            )
    return errors


def validate_grid(instrument: str, notes: List[dict], bp: dict = None) -> List[str]:
    """Drums sit on 16ths; pitched parts on 16ths or triplets."""
    grid = DRUM_GRID if instrument == "drums" else PITCHED_GRID
    name = "16th-note" if instrument == "drums" else "16th/triplet"
    errors = []
    for ev in notes:
        steps = ev["start_beat"] / grid
        if abs(steps - round(steps)) > 1e-3:
            errors.append(f"{_at(instrument, ev, bp)}: start_beat {ev['start_beat']} is off the "
                          f"{name} grid")
    return errors


def validate_polyphony(instrument: str, notes: List[dict], bp: dict = None) -> List[str]:
    if instrument != "chords":
        return []
    for ev in notes:
        t = ev["start_beat"]
        sounding = [n for n in notes if n["start_beat"] <= t + EPS < n["start_beat"] + n["duration"]]
        if len(sounding) > MAX_CHORD_NOTES:
            return [f"{_at(instrument, ev, bp)}: {len(sounding)} notes at once "
                    f"(max {MAX_CHORD_NOTES})"]
    return []


def validate_sections(instrument: str, notes: List[dict], bp: dict) -> List[str]:
    """Respect the blueprint's instruments-per-section, and play where asked."""
    if instrument not in bp["instruments"]:
        return [f"{instrument} is not one of the blueprint's instruments {bp['instruments']}"]
    bars = bar_map(bp)
    errors = []
    silent_hits = {}
    for ev in notes:
        b = bar_of(bp, ev["start_beat"])
        if 1 <= b <= len(bars) and instrument not in bars[b - 1]["roles"]:
            silent_hits.setdefault(bars[b - 1]["section"], b)
    for section, b in silent_hits.items():
        errors.append(f"{instrument} plays in bar {b} ({section}) but the blueprint leaves "
                      f"{instrument} out of the {section} - remove those notes")
    if not notes and any(instrument in b["roles"] for b in bars):
        errors.append(f"{instrument} part is empty but the blueprint has {instrument} playing")
    return errors


# --------------------------------------------------------------------------- blueprint


def validate_blueprint(bp: dict) -> List[str]:
    errors = []
    for field in ("key", "mode", "tempo", "time_signature", "sections", "instruments"):
        if field not in bp:
            errors.append(f"Blueprint missing field: {field}")
    if "key" in bp and bp["key"] not in NOTE_TO_PC:
        errors.append(f"Unknown key: {bp['key']}")
    if "mode" in bp and bp["mode"] not in SCALE_INTERVALS:
        errors.append(f"Unknown mode: {bp['mode']}")
    if "tempo" in bp and not (isinstance(bp["tempo"], (int, float)) and 40 <= bp["tempo"] <= 240):
        errors.append(f"tempo must be 40-240 BPM, got {bp['tempo']}")
    if "time_signature" in bp:
        ts = bp["time_signature"]
        if not (isinstance(ts, list) and len(ts) == 2
                and all(isinstance(x, int) and x > 0 for x in ts)):
            errors.append(f"time_signature must be [int, int] with positive values, got {ts}")
        elif ts[1] != 4 or not 2 <= ts[0] <= 7:
            errors.append(f"time_signature must be 2/4 to 7/4 (beats are quarter notes), got {ts}")
    if "instruments" in bp:
        inst = bp["instruments"]
        unknown = [r for r in inst if r not in ROLES]
        if unknown:
            errors.append(f"unknown instruments {unknown}; use roles from {ROLES}")
        if not inst:
            errors.append("instruments must list at least one role")
        if len(set(inst)) != len(inst):
            errors.append("instruments has duplicates")
    for role, program in (bp.get("programs") or {}).items():
        if role not in ROLES or not isinstance(program, int) or not 0 <= program <= 127:
            errors.append(f"programs: {role} -> {program} must be a role and a GM program 0-127")

    key_ok = bp.get("key") in NOTE_TO_PC and bp.get("mode") in SCALE_INTERVALS
    scale = key_pitch_classes(bp["key"], bp["mode"]) if key_ok else None
    if "sections" in bp:
        if not bp["sections"]:
            errors.append("sections must not be empty")
        bar = 1
        for i, sec in enumerate(bp["sections"]):
            name = sec.get("name", i)
            for field in ("name", "bars", "chords"):
                if field not in sec:
                    errors.append(f"Section {i} missing field: {field}")
            if "bars" in sec and "chords" in sec and len(sec["chords"]) != sec["bars"]:
                errors.append(f"Section '{name}': {len(sec['chords'])} chords but {sec['bars']} bars")
            if "bars" in sec and (not isinstance(sec["bars"], int) or sec["bars"] < 1):
                errors.append(f"Section '{name}': bars must be a positive integer")
            if "energy" in sec and not 0 <= sec["energy"] <= 1:
                errors.append(f"Section '{name}': energy must be 0-1")
            extra = [r for r in sec.get("instruments", []) if r not in bp.get("instruments", [])]
            if extra:
                errors.append(f"Section '{name}': instruments {extra} are not in the "
                              f"blueprint's instruments")
            for j, symbol in enumerate(sec.get("chords", [])):
                try:
                    tones = chord_pitch_classes(symbol)
                except ValueError as e:
                    errors.append(f"bar {bar + j} ({name}): {e}")
                    continue
                if scale is not None and not tones <= scale:
                    outside = ", ".join(note_name(60 + pc)[:-1] for pc in sorted(tones - scale))
                    errors.append(f"bar {bar + j} ({name}): chord {symbol} uses {outside} which "
                                  f"is not in {bp['key']} {bp['mode']}; use chords built from the key")
            bar += sec["bars"] if isinstance(sec.get("bars"), int) else 0
    return errors


# --------------------------------------------------------------------------- part


def validate_part(instrument: str, notes: List[dict], blueprint: dict) -> List[str]:
    """Full validation of one instrument's notes against the blueprint."""
    if not isinstance(notes, list):
        return ["part notes must be a list"]
    errors = []
    for ev in notes:
        errors.extend(validate_note_event(ev))
    if errors:
        return errors  # the checks below assume well-formed notes
    bp = blueprint
    errors.extend(validate_notes_in_range(instrument, notes, bp))
    errors.extend(validate_notes_in_key(instrument, notes, bp["key"], bp["mode"], bp))
    errors.extend(validate_bar_lengths(instrument, notes, total_beats(bp)))
    errors.extend(validate_no_overlaps(instrument, notes))
    errors.extend(validate_monophonic(instrument, notes, bp))
    errors.extend(validate_grid(instrument, notes, bp))
    errors.extend(validate_polyphony(instrument, notes, bp))
    errors.extend(validate_sections(instrument, notes, bp))
    return errors


# --------------------------------------------------------------------------- fixing


def normalize_part(instrument: str, notes: List[dict], bp: dict) -> List[dict]:
    """Fix small slips an agent shouldn't be bothered with: numbers as floats, starts a
    hair off the grid, a note ringing a fraction past the end of the song."""
    grid = DRUM_GRID if instrument == "drums" else PITCHED_GRID
    song_end = total_beats(bp)
    out = []
    for ev in notes:
        try:
            n = {
                "pitch": int(round(float(ev["pitch"]))),
                "start_beat": float(ev["start_beat"]),
                "duration": float(ev["duration"]),
                "velocity": int(round(float(ev["velocity"]))),
            }
        except (KeyError, TypeError, ValueError, OverflowError):
            out.append(ev)  # leave it for the validator to report
            continue
        if not all(math.isfinite(value) for value in n.values()):
            out.append(ev)
            continue
        snapped = round(n["start_beat"] / grid) * grid
        if abs(snapped - n["start_beat"]) <= 0.06:
            n["start_beat"] = round(snapped, 6)
        overshoot = n["start_beat"] + n["duration"] - song_end
        if 0 < overshoot <= 0.5:
            n["duration"] = round(song_end - n["start_beat"], 6)
        out.append(n)
    if any(validate_note_event(ev) for ev in out):
        return out  # malformed notes remain intact for actionable validation errors
    return sorted(out, key=lambda e: (e["start_beat"], e["pitch"]))


def repair_part(instrument: str, notes: List[dict], bp: dict) -> Tuple[List[dict], List[str]]:
    """Last resort: make a part valid by moving or dropping the notes that break rules.
    Returns (notes, what was changed)."""
    fixes: List[str] = []
    lo, hi = PITCH_RANGES.get(instrument, (0, 127))
    scale = key_pitch_classes(bp["key"], bp["mode"])
    bars = bar_map(bp)
    song_end = total_beats(bp)
    grid = DRUM_GRID if instrument == "drums" else PITCHED_GRID

    kept = []
    for ev in normalize_part(instrument, notes, bp):
        if validate_note_event(ev):
            fixes.append(f"dropped malformed note {ev}")
            continue
        ev = dict(ev)
        ev["start_beat"] = round(round(ev["start_beat"] / grid) * grid, 6)
        while ev["pitch"] < lo:
            ev["pitch"] += 12
        while ev["pitch"] > hi:
            ev["pitch"] -= 12
        b = bar_of(bp, ev["start_beat"])
        if ev["start_beat"] >= song_end or instrument not in bars[min(b, len(bars)) - 1]["roles"]:
            fixes.append(f"dropped note at {where(bp, ev['start_beat'])}")
            continue
        if instrument != "drums" and ev["pitch"] % 12 not in scale:
            fixes.append(f"dropped out-of-key {note_name(ev['pitch'])} at {where(bp, ev['start_beat'])}")
            continue
        ev["duration"] = min(ev["duration"], song_end - ev["start_beat"])
        kept.append(ev)

    # one note per (onset, pitch); monophonic parts keep one note per onset
    unique = {}
    for ev in sorted(kept, key=lambda e: (e["start_beat"], e["pitch"])):
        key = ev["start_beat"] if instrument in MONOPHONIC else (ev["start_beat"], ev["pitch"])
        if key not in unique:
            unique[key] = ev
        elif instrument == "melody":
            unique[key] = ev  # sorted by pitch, so the top note wins for melody
    if len(unique) < len(kept):
        fixes.append(f"removed {len(kept) - len(unique)} doubled notes")
    notes_out = sorted(unique.values(), key=lambda e: (e["start_beat"], e["pitch"]))

    # trim notes that still sound when the next note in the same voice starts
    for i, ev in enumerate(notes_out):
        for later in notes_out[i + 1:]:
            same_voice = instrument in MONOPHONIC or later["pitch"] == ev["pitch"]
            end = ev["start_beat"] + ev["duration"]
            if same_voice and ev["start_beat"] < later["start_beat"] < end - EPS:
                ev["duration"] = round(later["start_beat"] - ev["start_beat"], 6)
                fixes.append(f"shortened note at {where(bp, ev['start_beat'])}")
                break

    if instrument == "chords":  # cap how many notes ring at once
        capped = []
        for ev in notes_out:
            ringing = [n for n in capped
                       if n["start_beat"] <= ev["start_beat"] < n["start_beat"] + n["duration"]]
            if len(ringing) < MAX_CHORD_NOTES:
                capped.append(ev)
        notes_out = capped
    return notes_out, fixes
