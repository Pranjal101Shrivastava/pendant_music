"""Music theory helpers: note names, keys and chord symbols.

Pitches are MIDI numbers (60 = C4). Pitch classes are 0-11 with C = 0.
"""

import re
from typing import List, Set, Tuple

NOTE_TO_PC = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
    "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}

SCALE_INTERVALS = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
}

ROLES = ["drums", "bass", "chords", "melody"]

SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

# General MIDI drum map (channel 10) for the notes the drum agent uses most
DRUM_NAMES = {
    35: "kick2", 36: "kick", 37: "rim", 38: "snare", 39: "clap", 40: "snare2",
    42: "closed hat", 44: "pedal hat", 46: "open hat", 49: "crash", 51: "ride",
    41: "low tom", 45: "mid tom", 48: "high tom", 54: "tambourine", 56: "cowbell",
    70: "shaker", 75: "claves",
}

# chord suffix -> intervals above the root
CHORD_QUALITIES = {
    "": (0, 4, 7), "maj": (0, 4, 7), "m": (0, 3, 7), "min": (0, 3, 7),
    "dim": (0, 3, 6), "aug": (0, 4, 8), "5": (0, 7),
    "7": (0, 4, 7, 10), "maj7": (0, 4, 7, 11), "m7": (0, 3, 7, 10),
    "m7b5": (0, 3, 6, 10), "dim7": (0, 3, 6, 9), "mmaj7": (0, 3, 7, 11),
    "sus2": (0, 2, 7), "sus4": (0, 5, 7), "7sus4": (0, 5, 7, 10),
    "6": (0, 4, 7, 9), "m6": (0, 3, 7, 9), "add9": (0, 2, 4, 7), "madd9": (0, 2, 3, 7),
    "9": (0, 2, 4, 7, 10), "m9": (0, 2, 3, 7, 10), "maj9": (0, 2, 4, 7, 11),
}

_CHORD_RE = re.compile(r"^([A-G][#b]?)([^/]*)(?:/([A-G][#b]?))?$")


def key_pitch_classes(key: str, mode: str) -> Set[int]:
    root = NOTE_TO_PC[key]
    return {(root + i) % 12 for i in SCALE_INTERVALS[mode]}


def note_name(pitch: int, flats: bool = False) -> str:
    """60 -> 'C4'."""
    names = FLAT_NAMES if flats else SHARP_NAMES
    return f"{names[pitch % 12]}{pitch // 12 - 1}"


def uses_flats(key: str, mode: str) -> bool:
    """Spell notes with flats in flat keys (F major, D minor, Bb, Eb, ...)."""
    if "b" in key or "#" in key:
        return "b" in key
    major_root = (NOTE_TO_PC[key] + (3 if mode == "minor" else 0)) % 12
    return major_root in {5, 10, 3, 8, 1, 6}  # F Bb Eb Ab Db Gb


def parse_chord(symbol: str) -> Tuple[int, Tuple[int, ...], int]:
    """'Am7' -> (root pc, intervals, bass pc). Raises ValueError on unknown symbols."""
    m = _CHORD_RE.match(symbol.strip())
    if not m or m.group(2) not in CHORD_QUALITIES:
        raise ValueError(
            f"unknown chord symbol {symbol!r}; use a root (C, F#, Bb...) plus one of "
            f"{', '.join(repr(q) for q in CHORD_QUALITIES if q)} or nothing for major"
        )
    root = NOTE_TO_PC[m.group(1)]
    bass = NOTE_TO_PC[m.group(3)] if m.group(3) else root
    return root, CHORD_QUALITIES[m.group(2)], bass


def chord_pitch_classes(symbol: str) -> Set[int]:
    root, intervals, bass = parse_chord(symbol)
    return {(root + i) % 12 for i in intervals} | {bass}


def chord_root(symbol: str) -> int:
    return parse_chord(symbol)[0]


def diatonic_chords(key: str, mode: str) -> List[str]:
    """The seven triads built on the scale, e.g. C major -> C Dm Em F G Am Bdim."""
    root = NOTE_TO_PC[key]
    flats = uses_flats(key, mode)
    steps = SCALE_INTERVALS[mode]
    chords = []
    for degree in range(7):
        r = steps[degree]
        third = (steps[(degree + 2) % 7] - r) % 12
        fifth = (steps[(degree + 4) % 7] - r) % 12
        quality = {(4, 7): "", (3, 7): "m", (3, 6): "dim", (4, 8): "aug"}[(third, fifth)]
        name = (FLAT_NAMES if flats else SHARP_NAMES)[(root + r) % 12]
        chords.append(name + quality)
    return chords


def pitch_in_range(pc: int, lo: int, hi: int, near: int) -> int:
    """The pitch with class pc inside [lo, hi] closest to `near`."""
    candidates = [p for p in range(lo, hi + 1) if p % 12 == pc]
    return min(candidates, key=lambda p: abs(p - near))
