"""Shared data contract. Every agent reads and writes these plain dicts (JSON-friendly).

Timing: a beat is a quarter note; start_beat counts from 0 at the start of the song.
Bars are 1-based in messages: bar 1 covers beats 0-4 in 4/4.
"""

from typing import Dict, List

from typing_extensions import NotRequired, TypedDict


class NoteEvent(TypedDict):
    pitch: int          # MIDI pitch 0-127 (drums: General MIDI drum-map note)
    start_beat: float   # beat number, 0-indexed
    duration: float     # in beats, > 0
    velocity: int       # 1-127


class Section(TypedDict):
    name: str
    bars: int
    chords: List[str]   # one chord label per bar e.g. "Cm", "G7"
    energy: NotRequired[float]            # 0 = sparse/quiet .. 1 = full/loud (default 0.5)
    instruments: NotRequired[List[str]]   # roles playing in this section (default: all)


class Blueprint(TypedDict):
    key: str                    # root note e.g. "C", "F#", "Bb"
    mode: str                   # "major" or "minor"
    tempo: float                # BPM
    time_signature: List[int]   # [numerator, denominator]
    sections: List[Section]
    instruments: List[str]
    title: NotRequired[str]
    style: NotRequired[str]                 # genre + mood, e.g. "sad lo-fi"
    programs: NotRequired[Dict[str, int]]   # role -> General MIDI program


class Song(TypedDict):
    """What core.midi_writer.write_midi consumes."""
    tempo: float
    instruments: Dict[str, List[NoteEvent]]   # role -> notes
    time_signature: NotRequired[List[int]]
    programs: NotRequired[Dict[str, int]]


def make_song(blueprint: Blueprint, parts: Dict[str, List[NoteEvent]]) -> Song:
    return {
        "tempo": blueprint["tempo"],
        "time_signature": blueprint["time_signature"],
        "programs": dict(blueprint.get("programs", {})),
        "instruments": {role: parts[role] for role in blueprint["instruments"] if role in parts},
    }
