import os
import tempfile
import pretty_midi
from core.midi_writer import write_midi

SAMPLE = {
    "tempo": 120,
    "instruments": {
        "drums": [
            {"pitch": 36, "start_beat": 0, "duration": 0.25, "velocity": 100},
            {"pitch": 38, "start_beat": 1, "duration": 0.25, "velocity": 80},
        ],
        "bass": [
            {"pitch": 40, "start_beat": 0, "duration": 2.0, "velocity": 90},
        ],
    },
}


def test_file_is_created():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "out.mid")
        write_midi(SAMPLE, path)
        assert os.path.exists(path)


def test_instrument_count():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "out.mid")
        write_midi(SAMPLE, path)
        midi = pretty_midi.PrettyMIDI(path)
        assert len(midi.instruments) == 2


def test_drum_track_flagged_as_drum():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "out.mid")
        write_midi(SAMPLE, path)
        midi = pretty_midi.PrettyMIDI(path)
        drums = next(i for i in midi.instruments if i.name == "drums")
        assert drums.is_drum


def test_note_count():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "out.mid")
        write_midi(SAMPLE, path)
        midi = pretty_midi.PrettyMIDI(path)
        total = sum(len(i.notes) for i in midi.instruments)
        assert total == 3


def test_tempo_is_preserved():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "out.mid")
        write_midi(SAMPLE, path)
        midi = pretty_midi.PrettyMIDI(path)
        _, tempos = midi.get_tempo_changes()
        assert abs(tempos[0] - 120.0) < 1.0


def test_non_drum_track_not_flagged():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "out.mid")
        write_midi(SAMPLE, path)
        midi = pretty_midi.PrettyMIDI(path)
        bass = next(i for i in midi.instruments if i.name == "bass")
        assert not bass.is_drum
