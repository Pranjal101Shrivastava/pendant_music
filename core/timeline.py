"""Where things are in a song: bars, beats, sections and chords from a blueprint."""

from typing import Dict, List

from core.theory import ROLES


def beats_per_bar(bp: dict) -> int:
    return int(bp["time_signature"][0])


def total_bars(bp: dict) -> int:
    return sum(sec["bars"] for sec in bp["sections"])


def bar_of(bp: dict, beat: float) -> int:
    """1-based bar containing a 0-based beat."""
    return int(beat // beats_per_bar(bp)) + 1


def where(bp: dict, beat: float) -> str:
    """0-based beat -> 'bar 3 beat 2.5' (both 1-based, like musicians count)."""
    bar = bar_of(bp, beat)
    in_bar = beat - (bar - 1) * beats_per_bar(bp) + 1
    return f"bar {bar} beat {in_bar:g}"


def section_roles(bp: dict, section: dict) -> List[str]:
    return list(section.get("instruments") or bp["instruments"])


def bar_map(bp: dict) -> List[Dict]:
    """One entry per bar: bar number, section, chord, energy, roles playing, first beat."""
    bars = []
    n = 1
    for sec in bp["sections"]:
        for i in range(sec["bars"]):
            chords = sec.get("chords") or []
            bars.append({
                "bar": n,
                "section": sec["name"],
                "chord": chords[i] if i < len(chords) else (chords[-1] if chords else "C"),
                "energy": float(sec.get("energy", 0.5)),
                "roles": section_roles(bp, sec),
                "start_beat": (n - 1) * beats_per_bar(bp),
                "first_in_section": i == 0,
                "last_in_section": i == sec["bars"] - 1,
            })
            n += 1
    return bars


def roles_in_order(bp: dict) -> List[str]:
    """Blueprint instruments in the default writing order: drums, bass, chords, melody."""
    return [r for r in ROLES if r in bp["instruments"]]
