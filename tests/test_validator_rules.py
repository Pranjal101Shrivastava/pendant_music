"""Rules added on top of the phase 2 validator (tests/test_validator.py covers the rest)."""

import copy
import pytest

from core.validator import (
    normalize_part,
    repair_part,
    validate_blueprint,
    validate_grid,
    validate_monophonic,
    validate_part,
    validate_polyphony,
    validate_sections,
)
from tests.helpers import BLUEPRINT, note


def test_errors_say_where_the_problem_is():
    errs = validate_part("melody", [note(61, 5.5)], BLUEPRINT)
    assert any("bar 2 beat 2.5" in e and "C#4" in e for e in errs)


def test_bass_and_melody_play_one_note_at_a_time():
    assert validate_monophonic("bass", [note(48, 0, 2), note(43, 1)], BLUEPRINT)
    assert validate_monophonic("bass", [note(48, 0, 1), note(43, 1)], BLUEPRINT) == []
    assert validate_monophonic("chords", [note(48, 0, 2), note(52, 0, 2)], BLUEPRINT) == []


def test_drums_on_16ths_pitched_on_16ths_or_triplets():
    assert validate_grid("drums", [note(36, 0.3, 0.25)], BLUEPRINT)
    assert validate_grid("drums", [note(36, 0.75, 0.25)], BLUEPRINT) == []
    assert validate_grid("melody", [note(60, 1 / 3)], BLUEPRINT) == []
    assert validate_grid("melody", [note(60, 0.1)], BLUEPRINT)


def test_chords_max_six_notes():
    seven = [note(p, 0, 4) for p in (48, 52, 55, 60, 64, 67, 72)]
    assert validate_polyphony("chords", seven, BLUEPRINT)


def test_instruments_per_section():
    bp = copy.deepcopy(BLUEPRINT)
    bp["sections"][0]["instruments"] = ["chords"]
    errs = validate_sections("melody", [note(60, 0)], bp)
    assert any("verse" in e and "remove" in e for e in errs)
    assert validate_sections("melody", [], BLUEPRINT)  # empty but expected to play


def test_blueprint_chords_must_fit_the_key():
    bp = copy.deepcopy(BLUEPRINT)
    bp["sections"][0]["chords"] = ["C", "E7"]
    errs = validate_blueprint(bp)
    assert any("E7" in e and "G#" in e for e in errs)
    bp["sections"][0]["chords"] = ["C", "Cfoo"]
    assert any("unknown chord" in e for e in validate_blueprint(bp))


def test_blueprint_meter_and_sections():
    bp = copy.deepcopy(BLUEPRINT)
    bp["time_signature"] = [6, 8]
    assert any("2/4 to 7/4" in e for e in validate_blueprint(bp))
    bp = copy.deepcopy(BLUEPRINT)
    bp["sections"][1]["instruments"] = ["theremin"]
    assert validate_blueprint(bp)


def test_normalize_snaps_small_slips():
    fixed = normalize_part("drums", [{"pitch": 36.0, "start_beat": 1.02, "duration": 0.25, "velocity": 99.6}], BLUEPRINT)
    assert fixed == [note(36, 1.0, 0.25, 100)]


def test_repair_makes_any_part_valid():
    messy = [note(20, 0, 2), note(61, 1), note(64, 1.5, 2), note(67, 2), note(72, 15.5, 3), note(60, 20)]
    repaired, fixes = repair_part("melody", messy, BLUEPRINT)
    assert validate_part("melody", repaired, BLUEPRINT) == []
    assert fixes


@pytest.mark.parametrize('event', [None, 'bad note', {'pitch': 'C4', 'start_beat': 0, 'duration': 1, 'velocity': 80},
                                    {'pitch': 60, 'start_beat': float('inf'), 'duration': 1, 'velocity': 80},
                                    {'pitch': 60, 'start_beat': 0, 'duration': float('nan'), 'velocity': 80}])
def test_malformed_notes_report_errors_instead_of_crashing(event):
    from core.validator import normalize_part, validate_note_event
    from tests.helpers import BLUEPRINT
    notes = normalize_part('melody', [event], BLUEPRINT)
    assert validate_note_event(notes[0])
