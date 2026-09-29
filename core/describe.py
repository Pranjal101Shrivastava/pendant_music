"""Compact text views of a blueprint and parts, for agent prompts and for people."""

import json
from collections import defaultdict
from typing import Dict, List

from core.theory import DRUM_NAMES, note_name, uses_flats
from core.timeline import bar_map, bar_of, beats_per_bar


def describe_blueprint(bp: dict) -> str:
    lines = ["Blueprint JSON:", json.dumps(bp, indent=1), "", "Bar map (bar | section | chord | energy | playing):"]
    for b in bar_map(bp):
        lines.append(f"  bar {b['bar']:>2} | {b['section']} | {b['chord']} | energy {b['energy']:g} | "
                     f"{', '.join(b['roles'])}")
    bpb = beats_per_bar(bp)
    lines.append(f"\n{len(bar_map(bp))} bars of {bpb} beats. start_beat for bar N, beat B "
                 f"(both 1-based) = (N - 1) * {bpb} + (B - 1).")
    return "\n".join(lines)


def _beat_in_bar(bp: dict, start: float) -> str:
    b = bar_of(bp, start)
    return f"{start - (b - 1) * beats_per_bar(bp) + 1:g}"


def describe_part(role: str, notes: List[dict], bp: dict, bars: List[int] = None) -> str:
    """One line per bar. Pitched: 'A2@1(1.5)' = A2 on beat 1 for 1.5 beats.
    Drums: 'kick 1 2.5 | snare 2 4'."""
    flats = uses_flats(bp["key"], bp["mode"])
    chords = {b["bar"]: b["chord"] for b in bar_map(bp)}
    per_bar: Dict[int, List[dict]] = defaultdict(list)
    for ev in sorted(notes, key=lambda e: (e["start_beat"], e["pitch"])):
        per_bar[bar_of(bp, ev["start_beat"])].append(ev)
    lines = []
    for bar in sorted(chords):
        if bars and bar not in bars:
            continue
        evs = per_bar.get(bar, [])
        if not evs:
            lines.append(f"bar {bar} ({chords[bar]}): rest")
            continue
        if role == "drums":
            hits: Dict[str, List[str]] = defaultdict(list)
            for ev in evs:
                hits[DRUM_NAMES.get(ev["pitch"], str(ev["pitch"]))].append(_beat_in_bar(bp, ev["start_beat"]))
            body = " | ".join(f"{name} {' '.join(beats)}" for name, beats in hits.items())
        else:
            body = " ".join(f"{note_name(ev['pitch'], flats)}@{_beat_in_bar(bp, ev['start_beat'])}"
                            f"({ev['duration']:g})" for ev in evs)
        lines.append(f"bar {bar} ({chords[bar]}): {body}")
    return "\n".join(lines)


def describe_parts(parts: Dict[str, List[dict]], bp: dict) -> str:
    if not parts:
        return "(no other parts written yet)"
    return "\n\n".join(f"{role.upper()} part:\n{describe_part(role, notes, bp)}"
                       for role, notes in parts.items())
