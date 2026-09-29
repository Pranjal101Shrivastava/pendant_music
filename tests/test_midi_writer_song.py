import json
import os

import pretty_midi

from core.midi_writer import write_midi
from core.validator import validate_blueprint, validate_part

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples", "hand_written_song.json")


def test_hand_written_example_is_valid_and_renders(tmp_path):
    data = json.load(open(EXAMPLE))
    bp, song = data["blueprint"], data["song"]
    assert validate_blueprint(bp) == []
    for role, notes in song["instruments"].items():
        assert validate_part(role, notes, bp) == [], role
    path = str(tmp_path / "hand.mid")
    write_midi(song, path)
    midi = pretty_midi.PrettyMIDI(path)
    assert [i.name for i in midi.instruments] == ["drums", "bass", "chords", "melody"]
    assert {i.name: i.program for i in midi.instruments if not i.is_drum} == {"bass": 33, "chords": 4, "melody": 11}
    ts = midi.time_signature_changes[0]
    assert (ts.numerator, ts.denominator) == (4, 4)
    # beat 1 at 85 BPM = 0.7059 s
    melody = next(i for i in midi.instruments if i.name == "melody")
    assert abs(melody.notes[1].start - 60 / 85) < 1e-3


def test_three_four_time(tmp_path):
    path = str(tmp_path / "waltz.mid")
    write_midi({"tempo": 90, "time_signature": [3, 4],
                "instruments": {"melody": [{"pitch": 60, "start_beat": 0, "duration": 3, "velocity": 80}]}}, path)
    ts = pretty_midi.PrettyMIDI(path).time_signature_changes[0]
    assert (ts.numerator, ts.denominator) == (3, 4)
