"""Rule-based musicians: the offline stand-in for every model call.

They follow the same contract as the model-backed agents (same inputs, same JSON out),
so the pipeline, validator, critic loop and MIDI writer can all run without an API key.
They also make a baseline to compare model output against.
"""

import random
import re
import zlib
from typing import Dict, List

from core.analysis import analyze
from core.theory import (
    FLAT_NAMES,
    NOTE_TO_PC,
    SCALE_INTERVALS,
    SHARP_NAMES,
    chord_pitch_classes,
    chord_root,
    key_pitch_classes,
    pitch_in_range,
    uses_flats,
)
from core.timeline import bar_map, beats_per_bar, roles_in_order

# --------------------------------------------------------------------------- styles

GENRES = {
    "lofi": {"words": ["lo-fi", "lofi", "chill", "study", "hip-hop", "hip hop"], "mode": "minor",
             "keys": ["A", "D", "E", "C"], "tempo": 80, "sevenths": True,
             "progressions": [[1, 4, 7, 3], [1, 6, 4, 5], [4, 5, 1, 1]],
             "programs": {"bass": 33, "chords": 4, "melody": 11},
             "drums": "lofi", "chords": "sustain", "melody": "lazy"},
    "funk": {"words": ["funk", "funky", "groove", "disco"], "mode": "minor",
             "keys": ["E", "A", "D"], "tempo": 110, "sevenths": True,
             "progressions": [[1, 4, 1, 4], [1, 1, 4, 7], [4, 4, 1, 1]],
             "programs": {"bass": 36, "chords": 7, "melody": 61},
             "drums": "funk", "chords": "stabs", "melody": "riff"},
    "ambient": {"words": ["ambient", "dreamy", "drone", "atmospheric", "ethereal"], "mode": "major",
                "keys": ["C", "D", "F", "G"], "tempo": 70, "sevenths": True,
                "progressions": [[1, 6, 4, 5], [1, 4, 1, 4], [6, 4, 1, 5]],
                "programs": {"bass": 35, "chords": 89, "melody": 73},
                "drums": "ambient", "chords": "pad", "melody": "floating"},
    "jazz": {"words": ["jazz", "swing", "bebop", "bossa"], "mode": "major",
             "keys": ["F", "Bb", "C", "Eb"], "tempo": 130, "sevenths": True,
             "progressions": [[2, 5, 1, 1], [1, 6, 2, 5], [3, 6, 2, 5]],
             "programs": {"bass": 32, "chords": 0, "melody": 66},
             "drums": "swing", "chords": "comp", "melody": "bop"},
    "rock": {"words": ["rock", "punk", "grunge", "metal"], "mode": "major",
             "keys": ["E", "A", "D", "G"], "tempo": 120, "sevenths": False,
             "progressions": [[1, 4, 5, 4], [6, 4, 1, 5], [1, 5, 6, 4]],
             "programs": {"bass": 34, "chords": 29, "melody": 30},
             "drums": "rock", "chords": "power", "melody": "anthem"},
    "pop": {"words": ["pop", "happy", "upbeat", "dance"], "mode": "major",
            "keys": ["C", "G", "D", "F"], "tempo": 100, "sevenths": False,
            "progressions": [[1, 5, 6, 4], [1, 6, 4, 5], [6, 4, 1, 5]],
            "programs": {"bass": 33, "chords": 0, "melody": 80},
            "drums": "pop", "chords": "pulse", "melody": "hook"},
}
SAD_WORDS = ["sad", "dark", "melancholic", "moody", "lonely", "minor"]
HAPPY_WORDS = ["happy", "bright", "sunny", "joyful", "major"]
TITLE_A = ["Rainy", "Neon", "Velvet", "Golden", "Midnight", "Paper", "Quiet", "Electric", "Faded", "Silver"]
TITLE_B = ["Tape", "Window", "Streets", "Garden", "Signal", "Harbor", "Loop", "Skyline", "Echo", "Drive"]


def _rng(*parts) -> random.Random:
    return random.Random(zlib.crc32("|".join(str(p) for p in parts).encode()))


def pick_genre(prompt: str) -> str:
    text = prompt.lower()
    for name, g in GENRES.items():
        if any(w in text for w in g["words"]):
            return name
    return "pop"


def degree_chord(key: str, mode: str, degree: int, seventh: bool) -> str:
    """Diatonic chord on a scale degree (1-7), e.g. C major, 5, seventh -> 'G7'."""
    steps = SCALE_INTERVALS[mode]
    root = NOTE_TO_PC[key]
    r = steps[degree - 1]
    stack = [(steps[(degree - 1 + k) % 7] - r) % 12 for k in (2, 4, 6)]
    third, fifth, sev = stack
    triad = {(4, 7): "", (3, 7): "m", (3, 6): "dim", (4, 8): "aug"}[(third, fifth)]
    if seventh:
        quality = {("", 11): "maj7", ("", 10): "7", ("m", 10): "m7", ("dim", 10): "m7b5",
                   ("m", 11): "mmaj7", ("aug", 11): "maj7"}.get((triad, sev), triad)
    else:
        quality = triad
    names = FLAT_NAMES if uses_flats(key, mode) else SHARP_NAMES
    return names[(root + r) % 12] + quality


# --------------------------------------------------------------------------- composer


def compose(prompt: str, bars: int, seed: int, attempt: int = 0) -> dict:
    genre = pick_genre(prompt)
    g = GENRES[genre]
    rng = _rng("compose", prompt, seed, attempt)
    text = prompt.lower()
    mode = g["mode"]
    if any(w in text for w in SAD_WORDS):
        mode = "minor"
    elif any(w in text for w in HAPPY_WORDS) and genre not in ("lofi", "funk"):
        mode = "major"
    key = rng.choice(g["keys"])
    bpm = re.search(r"(\d{2,3})\s*bpm", text)
    tempo = int(bpm.group(1)) if bpm else g["tempo"]
    tempo = max(40, min(240, tempo))

    progs = g["progressions"][:]
    rng.shuffle(progs)
    verse_prog, chorus_prog = progs[0], progs[1]
    everyone = ["drums", "bass", "chords", "melody"]

    def chords_for(prog, n, end_on_tonic=False):
        out = [degree_chord(key, mode, prog[i % len(prog)], g["sevenths"]) for i in range(n)]
        if end_on_tonic:
            out[-1] = degree_chord(key, mode, 1, g["sevenths"])
        return out

    if bars <= 8:
        sections = [{"name": "verse", "bars": bars, "chords": chords_for(verse_prog, bars, True),
                     "energy": 0.6, "instruments": everyone}]
    else:
        edge = 4 if bars >= 16 else 2
        middle = bars - 2 * edge
        intro_roles = ["chords"] + (["drums"] if genre in ("funk", "rock") else [])
        sections = [{"name": "intro", "bars": edge, "chords": chords_for(verse_prog, edge),
                     "energy": 0.3, "instruments": intro_roles}]
        chunk = 8 if middle >= 16 else 4
        i = 0
        while middle > 0:
            n = min(chunk, middle)
            name = "verse" if i % 2 == 0 else "chorus"
            sections.append({"name": name if i < 2 else f"{name} {i // 2 + 1}", "bars": n,
                             "chords": chords_for(verse_prog if name == "verse" else chorus_prog, n),
                             "energy": 0.55 if name == "verse" else 0.85, "instruments": everyone})
            middle -= n
            i += 1
        sections.append({"name": "outro", "bars": edge, "chords": chords_for(verse_prog, edge, True),
                         "energy": 0.35, "instruments": ["bass", "chords", "melody"]})
        if genre == "ambient":
            sections[0]["instruments"] = ["chords"]
    title = f"{rng.choice(TITLE_A)} {rng.choice(TITLE_B)}"
    return {"title": title, "style": prompt.strip(), "key": key, "mode": mode, "tempo": tempo,
            "time_signature": [4, 4], "sections": sections, "instruments": everyone,
            "programs": dict(g["programs"])}


def _genre_of(bp: dict) -> dict:
    return GENRES[pick_genre(bp.get("style", "") + " " + bp.get("title", ""))]


# --------------------------------------------------------------------------- drums

# 16 steps per 4/4 bar. Each style: (kick, snare, hats, hat_pitch) per energy level low/high.
DRUM_STYLES = {
    "lofi":    {"kick": [0, 7, 10], "snare": [4, 12], "hat": list(range(0, 16, 2)), "hat_pitch": 42},
    "funk":    {"kick": [0, 3, 10], "snare": [4, 12], "ghost": [7, 9, 14], "hat": list(range(16)), "hat_pitch": 42},
    "ambient": {"kick": [0, 10], "snare": [12], "snare_pitch": 37, "hat": list(range(0, 16, 2)), "hat_pitch": 70},
    "swing":   {"kick": [0, 8], "snare": [], "hat": [0, 4, 6, 8, 12, 14], "hat_pitch": 51, "pedal": [4, 12]},
    "rock":    {"kick": [0, 6, 8], "snare": [4, 12], "hat": list(range(0, 16, 2)), "hat_pitch": 42},
    "pop":     {"kick": [0, 8, 10], "snare": [4, 12], "hat": list(range(0, 16, 2)), "hat_pitch": 42},
}


def play_drums(bp: dict, seed: int, variation: int) -> List[dict]:
    style = DRUM_STYLES[_genre_of(bp)["drums"]]
    bpb = beats_per_bar(bp)
    steps = bpb * 4
    notes = []
    rng = _rng("drums", seed, variation)

    def hit(pitch, start, vel):
        notes.append({"pitch": pitch, "start_beat": start, "duration": 0.25,
                      "velocity": max(1, min(127, int(vel)))})

    for b in bar_map(bp):
        if "drums" not in b["roles"]:
            continue
        o, e = b["start_beat"], b["energy"]
        scale = 0.7 + 0.4 * e
        if bpb != 4:  # simple pulse for other meters
            hit(36, o, 100 * scale)
            hit(38, o + max(1, bpb // 2), 85 * scale)
            for s in range(0, steps, 2):
                hit(style["hat_pitch"], o + s / 4, 60 * scale)
            continue
        kicks = style["kick"] if e >= 0.45 else style["kick"][:2]
        for s in kicks:
            hit(36, o + s / 4, (100 if s == 0 else 88) * scale)
        fill = b["last_in_section"] and e >= 0.45 and bp["sections"][-1]["name"] != b["section"]
        for s in style["snare"]:
            if fill and s >= 12:
                continue
            hit(style.get("snare_pitch", 38), o + s / 4, 90 * scale)
        for s in style.get("ghost", []):
            hit(38, o + s / 4, 38)
        hats = style["hat"]
        if e >= 0.8 and style["hat_pitch"] == 42 and len(hats) == 8:
            hats = list(range(16))  # busier hats in big sections
        for s in hats:
            accent = 1.0 if s % 4 == 0 else (0.85 if s % 2 == 0 else 0.7)
            hit(style["hat_pitch"], o + s / 4, (72 + rng.randint(-4, 4)) * accent * scale)
        for s in style.get("pedal", []):
            hit(44, o + s / 4, 60)
        if b["first_in_section"] and e >= 0.7:
            hit(49, o, 100)
        if fill:
            for s in range(12, 16):
                hit(38, o + s / 4, 70 + 8 * (s - 12))
    return notes


# --------------------------------------------------------------------------- bass


def play_bass(bp: dict, parts: Dict[str, List[dict]], seed: int, variation: int) -> List[dict]:
    g = _genre_of(bp)
    bpb = beats_per_bar(bp)
    kicks = sorted({round(ev["start_beat"], 3) for ev in parts.get("drums", []) if ev["pitch"] in (35, 36)})
    scale = sorted(key_pitch_classes(bp["key"], bp["mode"]))
    rng = _rng("bass", seed, variation)
    bars = bar_map(bp)
    notes = []
    for i, b in enumerate(bars):
        if "bass" not in b["roles"]:
            continue
        o, e = b["start_beat"], b["energy"]
        root = chord_root(b["chord"])
        tones = sorted(chord_pitch_classes(b["chord"]))
        fifth = (root + 7) % 12 if (root + 7) % 12 in tones else tones[len(tones) // 2]
        vel = int(80 + 25 * e)
        if g["drums"] == "swing":  # walking quarter notes toward the next root
            nxt = chord_root(bars[i + 1]["chord"]) if i + 1 < len(bars) else root
            pcs = [root, tones[1 % len(tones)], fifth]
            prev = pitch_in_range(root, 33, 52, 40)
            for beat in range(bpb):
                if beat == bpb - 1:  # approach note: scale step next to the next root
                    target = pitch_in_range(nxt, 33, 52, prev)
                    cands = [p for p in (target - 2, target - 1, target + 1, target + 2) if p % 12 in scale]
                    pitch = min(cands, key=lambda p: abs(p - prev)) if cands else target
                else:
                    pitch = pitch_in_range(pcs[beat % len(pcs)], 33, 52, prev)
                notes.append({"pitch": pitch, "start_beat": o + beat, "duration": 0.95, "velocity": vel})
                prev = pitch
            continue
        if g["chords"] == "pad":
            onsets = [0.0] if e < 0.7 else [0.0, bpb / 2]
        else:
            onsets = [round(k - o, 3) for k in kicks if o <= k < o + bpb] or [0.0, bpb / 2]
            if 0.0 not in onsets:
                onsets = [0.0] + onsets
        onsets = sorted(set(onsets))
        for j, t in enumerate(onsets):
            end = onsets[j + 1] if j + 1 < len(onsets) else bpb
            pc = root if (j == 0 or rng.random() < 0.6) else fifth
            pitch = pitch_in_range(pc, 33, 52, 40)
            if g["drums"] == "funk" and j > 0 and rng.random() < 0.3:
                pitch = min(pitch + 12, 60)  # octave pop
            dur = max(0.25, min(end - t, 2.0 if g["chords"] != "pad" else bpb) - 0.05)
            notes.append({"pitch": pitch, "start_beat": o + t, "duration": round(dur, 3), "velocity": vel})
    return notes


# --------------------------------------------------------------------------- chords


def _voicing(symbol: str, center: float, lo: int = 48, hi: int = 72) -> List[int]:
    pcs = chord_pitch_classes(symbol)
    return sorted({pitch_in_range(pc, lo, hi, int(center)) for pc in pcs})


def play_chords(bp: dict, seed: int, variation: int) -> List[dict]:
    g = _genre_of(bp)
    bpb = beats_per_bar(bp)
    rng = _rng("chords", seed, variation)
    notes = []
    center = 60.0
    for b in bar_map(bp):
        if "chords" not in b["roles"]:
            continue
        o, e = b["start_beat"], b["energy"]
        style = g["chords"] if e >= 0.45 else ("pad" if g["chords"] == "pad" else "sustain")
        if style == "power":
            root = pitch_in_range(chord_root(b["chord"]), 40, 52, 45)
            voicing = [root, root + 7, root + 12]
            if (root + 7) % 12 not in key_pitch_classes(bp["key"], bp["mode"]):
                voicing = [root, root + 12]
        else:
            voicing = _voicing(b["chord"], center)
            center = sum(voicing) / len(voicing)
        vel = int(55 + 30 * e)
        if style in ("sustain", "pad"):
            hits = [(0.0, float(bpb))]
        elif style == "stabs":
            hits = [(s / 4, 0.25) for s in (2, 6, 10, 14) if s / 4 < bpb]
        elif style == "pulse":
            hits = [(k * 0.5, 0.5) for k in range(bpb * 2)]
        elif style == "power":
            hits = [(k * 0.5, 0.5) for k in range(bpb * 2)]
        else:  # comp: Charleston plus a random push
            hits = [(0.0, 1.0), (1.5, 0.5)]
            if rng.random() < 0.5 and bpb >= 4:
                hits.append((3.5, 0.5))
        for t, d in hits:
            for p in voicing:
                notes.append({"pitch": p, "start_beat": o + t, "duration": d,
                              "velocity": vel + (6 if t == 0 else 0)})
    return notes


# --------------------------------------------------------------------------- melody

RHYTHMS = {  # (offset, duration) motifs for one 4/4 bar
    "lazy": [[(0, 1), (1, 0.5), (1.5, 0.5), (2, 1.5)], [(0.5, 0.5), (1, 1), (2.5, 1.5)]],
    "riff": [[(0, 0.5), (0.75, 0.25), (1.5, 0.5), (2.5, 0.5), (3, 0.5)], [(0, 0.25), (0.5, 0.5), (2, 1)]],
    "floating": [[(0, 2), (2, 2)], [(0, 3), (3, 1)]],
    "bop": [[(0, 0.5), (0.5, 0.5), (1, 0.5), (1.5, 0.5), (2, 1), (3.5, 0.5)], [(0.5, 0.5), (1, 0.5), (1.5, 1.5), (3, 1)]],
    "anthem": [[(0, 1), (1, 1), (2, 1.5), (3.5, 0.5)], [(0, 0.5), (0.5, 0.5), (1, 2)]],
    "hook": [[(0, 0.5), (0.5, 0.5), (1, 1), (2, 0.5), (2.5, 0.5), (3, 1)], [(0, 1.5), (1.5, 0.5), (2, 2)]],
}


def play_melody(bp: dict, seed: int, variation: int) -> List[dict]:
    g = _genre_of(bp)
    bpb = beats_per_bar(bp)
    rng = _rng("melody", seed, variation)
    scale_pcs = key_pitch_classes(bp["key"], bp["mode"])
    lo, hi = 62, 81
    scale = [p for p in range(lo, hi + 1) if p % 12 in scale_pcs]
    motifs = [m for m in RHYTHMS[g["melody"]]]
    rng.shuffle(motifs)
    notes = []
    prev = rng.choice([p for p in scale if 66 <= p <= 74])
    phrase_pos = 0
    for b in bar_map(bp):
        if "melody" not in b["roles"]:
            phrase_pos = 0
            continue
        o, e = b["start_beat"], b["energy"]
        tones = chord_pitch_classes(b["chord"])
        motif = motifs[0] if phrase_pos % 2 == 0 else motifs[1 % len(motifs)]
        motif = [(t, d) for t, d in motif if t + d <= bpb] or [(0, float(bpb))]
        phrase_end = b["last_in_section"] or phrase_pos % 4 == 3
        if phrase_end and len(motif) > 1:  # answer phrase: fewer notes, hold a chord tone
            head = motif[: max(1, len(motif) // 2)]
            motif = head[:-1] + [(head[-1][0], bpb - head[-1][0])]
        shift = 12 if e >= 0.8 and prev < 70 else 0
        for k, (t, d) in enumerate(motif):
            strong = abs(t % 1) < 1e-6
            candidates = [p for p in scale if (p % 12 in tones) or not strong]
            if k == len(motif) - 1 and phrase_end:
                candidates = [p for p in scale if p % 12 in tones]
            step = rng.choice([-2, -1, 1, 2, 0]) if not strong else rng.choice([-3, 0, 3])
            target = prev + step + shift
            pitch = min(candidates, key=lambda p: (abs(p - target), rng.random()))
            shift = 0
            dur = min(d, bpb - t)
            notes.append({"pitch": pitch, "start_beat": o + t, "duration": round(dur - 0.02, 3) if dur > 0.25 else dur,
                          "velocity": int(78 + 20 * e + (6 if strong else 0))})
            prev = pitch
        phrase_pos += 1
    return notes


# --------------------------------------------------------------------------- critic


def critique(bp: dict, parts: Dict[str, List[dict]], max_issues: int = 3) -> dict:
    a = analyze(bp, parts)
    issues = []
    serious = [p for p in a["problems"] if p["severity"] >= 0.3]
    for p in serious[:max_issues]:
        bars = sorted(p["bars"])
        first = bars[0]
        last = bars[-1] if bars[-1] - first < 8 else first + 7
        issues.append({"agent": p["agent"], "first_bar": first, "last_bar": last,
                       "problem": p["problem"], "fix": p["fix"]})
    verdict = "revise" if issues else "accept"
    summary = (f"Overall {a['overall']}/5. " +
               ("Sounds coherent." if verdict == "accept" else f"{len(issues)} thing(s) to fix."))
    return {"verdict": verdict, "scores": a["scores"], "summary": summary,
            "issues": issues if verdict == "revise" else []}


# --------------------------------------------------------------------------- dispatch


def play(role: str, bp: dict, parts: Dict[str, List[dict]], seed: int, variation: int) -> List[dict]:
    if role == "drums":
        return play_drums(bp, seed, variation)
    if role == "bass":
        return play_bass(bp, parts, seed, variation)
    if role == "chords":
        return play_chords(bp, seed, variation)
    if role == "melody":
        return play_melody(bp, seed, variation)
    raise ValueError(f"no offline player for {role}")


def respond(agent: str, schema_name: str, ctx: dict, attempt: int, seed: int) -> dict:
    """Answer the way a model would, for the request the agent made."""
    if schema_name == "blueprint":
        return compose(ctx["prompt"], ctx.get("bars", 8), seed, attempt)
    if schema_name in ("part", "part_with_feedback"):
        variation = attempt + 10 * ctx.get("revision", 0)
        notes = play(agent, ctx["blueprint"], ctx.get("parts", {}), seed, variation)
        if ctx.get("bars"):  # revising specific bars only
            wanted = set(ctx["bars"])
            bpb = beats_per_bar(ctx["blueprint"])
            notes = [n for n in notes if int(n["start_beat"] // bpb) + 1 in wanted]
        out = {"notes": notes}
        if schema_name == "part_with_feedback":
            out["feedback_to_composer"] = ""
        return out
    if schema_name == "critic_report":
        return critique(ctx["blueprint"], ctx["parts"], ctx.get("max_issues", 3))
    if schema_name == "arrangement":
        return {"order": roles_in_order(ctx["blueprint"]), "reason": "rhythm section first, then harmony, then the tune"}
    if schema_name == "blueprint_revision":
        return {"revise": False, "reason": "no feedback needed a change", "blueprint": ctx["blueprint"]}
    raise ValueError(f"offline musicians can't answer {schema_name!r}")
