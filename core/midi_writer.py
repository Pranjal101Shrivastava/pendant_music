"""Turns a song (note events per instrument) into a .mid file with pretty_midi.

    python -m core.midi_writer                                   # built-in 2-bar sample
    python -m core.midi_writer examples/hand_written_song.json   # any song JSON
"""

import json
import os
import sys

import pretty_midi

# General MIDI program numbers per instrument role (used when the song doesn't say)
_PROGRAMS = {
    "bass":   33,  # Electric Bass (finger)
    "chords":  0,  # Acoustic Grand Piano
    "melody":  0,  # Acoustic Grand Piano
}

_INSTRUMENT_ORDER = ["drums", "bass", "chords", "melody"]


def write_midi(song: dict, path: str) -> None:
    """Write a song dict to a MIDI file.

    song = {
        "tempo": 80,
        "time_signature": [4, 4],                 # optional, default 4/4
        "programs": {"bass": 33, "chords": 4},    # optional GM programs per role
        "instruments": {
            "drums":  [{"pitch": int, "start_beat": float, "duration": float, "velocity": int}, ...],
            "bass":   [...],
            "chords": [...],
            "melody": [...],
        }
    }
    Drums go on MIDI channel 10 (pretty_midi does this for is_drum tracks).
    """
    tempo = float(song.get("tempo", 120))
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    num, den = song.get("time_signature", [4, 4])
    midi.time_signature_changes.append(pretty_midi.TimeSignature(int(num), int(den), 0.0))
    spb = 60.0 / tempo  # seconds per beat
    programs = {**_PROGRAMS, **(song.get("programs") or {})}

    names = sorted(song["instruments"],
                   key=lambda n: _INSTRUMENT_ORDER.index(n) if n in _INSTRUMENT_ORDER else 99)
    for name in names:
        events = song["instruments"][name]
        is_drum = name == "drums"
        program = 0 if is_drum else int(programs.get(name, 0))
        track = pretty_midi.Instrument(program=program, is_drum=is_drum, name=name)
        for ev in events:
            start = ev["start_beat"] * spb
            end = start + max(ev["duration"], 0.01) * spb
            track.notes.append(pretty_midi.Note(
                velocity=int(ev["velocity"]),
                pitch=int(ev["pitch"]),
                start=start,
                end=end,
            ))
        midi.instruments.append(track)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    midi.write(path)


SAMPLE = {
    # 2-bar lo-fi beat at 80 BPM - kick/snare/hi-hat + bass
    "tempo": 80,
    "instruments": {
        "drums": [
            # kick on beats 1 and 3
            {"pitch": 36, "start_beat": 0,   "duration": 0.25, "velocity": 100},
            {"pitch": 36, "start_beat": 2,   "duration": 0.25, "velocity": 100},
            {"pitch": 36, "start_beat": 4,   "duration": 0.25, "velocity": 100},
            {"pitch": 36, "start_beat": 6,   "duration": 0.25, "velocity": 100},
            # snare on beats 2 and 4
            {"pitch": 38, "start_beat": 1,   "duration": 0.25, "velocity": 80},
            {"pitch": 38, "start_beat": 3,   "duration": 0.25, "velocity": 80},
            {"pitch": 38, "start_beat": 5,   "duration": 0.25, "velocity": 80},
            {"pitch": 38, "start_beat": 7,   "duration": 0.25, "velocity": 80},
            # closed hi-hat every half beat
            *[{"pitch": 42, "start_beat": i * 0.5, "duration": 0.25, "velocity": 60}
              for i in range(16)],
        ],
        "bass": [
            {"pitch": 40, "start_beat": 0, "duration": 1.5, "velocity": 90},
            {"pitch": 40, "start_beat": 2, "duration": 1.5, "velocity": 90},
            {"pitch": 43, "start_beat": 4, "duration": 1.5, "velocity": 90},
            {"pitch": 43, "start_beat": 6, "duration": 1.5, "velocity": 90},
        ],
    },
}


if __name__ == "__main__":
    here = os.path.dirname(__file__)
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            song = json.load(f)
        song = song.get("song", song)  # accept pipeline output files too
        stem = os.path.splitext(os.path.basename(sys.argv[1]))[0]
        out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "..", "outputs", f"{stem}.mid")
    else:
        song = SAMPLE
        out = os.path.join(here, "..", "outputs", "sample.mid")
    write_midi(song, out)
    print(f"Written: {os.path.abspath(out)}")
