"""Objective measurements of an assembled song, used by the critic.

The rubric from the plan (groove, harmonic fit, variation, balance) is scored 1-5 from
numbers code can measure. The LLM critic gets these numbers as data; the offline critic
turns them straight into issues.
"""

from collections import defaultdict
from typing import Dict, List

from core.theory import chord_pitch_classes, chord_root
from core.timeline import bar_map, bar_of, beats_per_bar

KICKS = {35, 36}
SNARES = {37, 38, 39, 40}
HATS = {42, 44, 46, 51}


def _by_bar(bp: dict, notes: List[dict]) -> Dict[int, List[dict]]:
    out: Dict[int, List[dict]] = defaultdict(list)
    for ev in notes:
        out[bar_of(bp, ev["start_beat"])].append(ev)
    return out


def _clamp_score(x: float) -> float:
    return round(max(1.0, min(5.0, x)), 1)


def analyze(bp: dict, parts: Dict[str, List[dict]]) -> dict:
    bars = bar_map(bp)
    bpb = beats_per_bar(bp)
    problems: List[dict] = []
    details: Dict[str, float] = {}

    # ---- groove: drums keep time, bass locks to the kick
    groove_parts = []
    drums = _by_bar(bp, parts.get("drums", []))
    drum_bars = [b for b in bars if "drums" in b["roles"]]
    if drum_bars:
        solid = []
        for b in drum_bars:
            evs = drums.get(b["bar"], [])
            starts = {(e["pitch"], round(e["start_beat"] - b["start_beat"], 3)) for e in evs}
            has_downbeat = any(p in KICKS and t == 0 for p, t in starts)
            backbeats = [1, 3] if bpb == 4 else [bpb - 1]
            has_backbeat = any(p in SNARES and t in backbeats for p, t in starts)
            pulse = sum(1 for p, _ in starts if p in HATS) >= bpb
            solid.append((has_downbeat + has_backbeat + pulse) / 3)
        groove_parts.append(sum(solid) / len(solid))
        details["drum_pattern_strength"] = round(groove_parts[-1], 2)
        weak = [b["bar"] for b, s in zip(drum_bars, solid) if s < 0.34]
        if weak:
            problems.append({"agent": "drums", "bars": weak, "severity": len(weak) / len(drum_bars),
                             "problem": "no steady beat (missing downbeat kick, backbeat snare or a hat pulse)",
                             "fix": "kick on beat 1, snare/clap on the backbeat, hats keeping 8ths"})
    bass = parts.get("bass", [])
    kick_times = {round(e["start_beat"], 3) for e in parts.get("drums", []) if e["pitch"] in KICKS}
    if bass and kick_times:
        locked = sum(1 for e in bass if round(e["start_beat"], 3) in kick_times) / len(bass)
        kicks_covered = sum(1 for t in kick_times if any(abs(e["start_beat"] - t) < 1e-3 for e in bass))
        lock = (locked + kicks_covered / len(kick_times)) / 2
        details["bass_kick_lock"] = round(lock, 2)
        groove_parts.append(lock)
        if lock < 0.35:
            problems.append({"agent": "bass", "bars": [b["bar"] for b in bars if "bass" in b["roles"]],
                             "severity": 1 - lock,
                             "problem": f"bass rarely lands with the kick (lock {lock:.0%})",
                             "fix": "start bass notes on the kick drum hits"})
    groove = _clamp_score(1 + 4 * (sum(groove_parts) / len(groove_parts))) if groove_parts else 3.0

    # ---- harmonic fit: strong-beat notes are chord tones; bass downbeats are roots
    fits = []
    for role in ("bass", "chords", "melody"):
        per_bar = _by_bar(bp, parts.get(role, []))
        bad_bars, good, total = [], 0, 0
        for b in bars:
            tones = chord_pitch_classes(b["chord"])
            strong = [e for e in per_bar.get(b["bar"], [])
                      if abs((e["start_beat"] - b["start_beat"]) % 1) < 1e-6]
            hits = sum(1 for e in strong if e["pitch"] % 12 in tones)
            good += hits
            total += len(strong)
            if strong and hits / len(strong) < 0.5:
                bad_bars.append(b["bar"])
        if total:
            ratio = good / total
            details[f"{role}_chord_tone_ratio"] = round(ratio, 2)
            fits.append(ratio)
            if bad_bars and ratio < 0.7:
                problems.append({"agent": role, "bars": bad_bars, "severity": 1 - ratio,
                                 "problem": f"{role} strong beats are often not chord tones",
                                 "fix": "put chord tones on the beats; use other scale notes in between"})
    bass_bars = _by_bar(bp, bass)
    downbeats = [(b, min(bass_bars[b["bar"]], key=lambda e: e["start_beat"]))
                 for b in bars if bass_bars.get(b["bar"])]
    if downbeats:
        rooted = sum(1 for b, e in downbeats
                     if e["start_beat"] == b["start_beat"] and e["pitch"] % 12 == chord_root(b["chord"]))
        details["bass_roots_on_downbeat"] = round(rooted / len(downbeats), 2)
        fits.append(rooted / len(downbeats))
    harmonic = _clamp_score(1 + 4 * (sum(fits) / len(fits))) if fits else 3.0

    # ---- variation: melody not stuck on one bar, sections sound different
    var_parts = []
    melody_bars = _by_bar(bp, parts.get("melody", []))
    shapes = []
    for b in bars:
        evs = sorted(melody_bars.get(b["bar"], []), key=lambda e: e["start_beat"])
        if evs:
            shapes.append(tuple((round(e["start_beat"] - b["start_beat"], 3), e["pitch"]) for e in evs))
    if len(shapes) >= 2:
        distinct = len(set(shapes)) / len(shapes)
        details["melody_distinct_bars"] = round(distinct, 2)
        var_parts.append(min(1.0, distinct / 0.6))
        if distinct < 0.35:
            problems.append({"agent": "melody", "bars": [b["bar"] for b in bars if b["bar"] in melody_bars],
                             "severity": 1 - distinct,
                             "problem": f"melody repeats the same bar too much ({distinct:.0%} distinct)",
                             "fix": "keep the motif but vary its ending, rhythm or pitch in later bars"})
    sections = {}
    for b in bars:
        count = sum(len(_by_bar(bp, notes).get(b["bar"], [])) for notes in parts.values())
        sections.setdefault(b["section"], []).append((b["energy"], count))
    if len(sections) >= 2:
        dens = {name: (vals[0][0], sum(c for _, c in vals) / len(vals)) for name, vals in sections.items()}
        ordered = sorted(dens.values())
        follows = all(d2 >= d1 * 0.9 for (_, d1), (_, d2) in zip(ordered, ordered[1:]))
        details["density_follows_energy"] = float(follows)
        var_parts.append(1.0 if follows else 0.4)
    variation = _clamp_score(1 + 4 * (sum(var_parts) / len(var_parts))) if var_parts else 3.0

    # ---- balance: everyone plays where asked, melody sits above the chords, not too crowded
    bal = []
    for role, notes in parts.items():
        per_bar = _by_bar(bp, notes)
        expected = [b["bar"] for b in bars if role in b["roles"]]
        if expected:
            empty = [n for n in expected if not per_bar.get(n)]
            bal.append(1 - len(empty) / len(expected))
            if len(empty) > len(expected) / 2:
                problems.append({"agent": role, "bars": empty, "severity": len(empty) / len(expected),
                                 "problem": f"{role} is silent in most bars where it should play",
                                 "fix": "play in every bar of the sections you are in"})
    chords_notes, melody_notes = parts.get("chords", []), parts.get("melody", [])
    if chords_notes and melody_notes:
        gap = (sum(e["pitch"] for e in melody_notes) / len(melody_notes)
               - sum(e["pitch"] for e in chords_notes) / len(chords_notes))
        details["melody_above_chords_semitones"] = round(gap, 1)
        bal.append(1.0 if gap >= 5 else max(0.0, (gap + 7) / 12))
        if gap < 3:
            problems.append({"agent": "chords", "bars": [b["bar"] for b in bars if "chords" in b["roles"]],
                             "severity": 0.6, "problem": "chords sit in the melody's register",
                             "fix": "voice chords lower (around C3-C5) so the melody stays on top"})
    busiest = max((len(evs) for notes in parts.values() for evs in _by_bar(bp, notes).values()), default=0)
    details["max_notes_in_a_bar"] = busiest
    balance = _clamp_score(1 + 4 * (sum(bal) / len(bal))) if bal else 3.0

    problems.sort(key=lambda p: -p["severity"])
    scores = {"groove": groove, "harmonic_fit": harmonic, "variation": variation, "balance": balance}
    return {"scores": scores, "overall": round(sum(scores.values()) / 4, 2),
            "details": details, "problems": problems}
