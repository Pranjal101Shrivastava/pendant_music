from core.validator import (
    key_pitch_classes,
    total_beats,
    validate_note_event,
    validate_notes_in_range,
    validate_notes_in_key,
    validate_bar_lengths,
    validate_no_overlaps,
    validate_blueprint,
    validate_part,
)

BLUEPRINT = {
    "key": "C",
    "mode": "major",
    "tempo": 80,
    "time_signature": [4, 4],
    "sections": [{"name": "verse", "bars": 4, "chords": ["C", "Am", "F", "G"]}],
    "instruments": ["drums", "bass", "melody"],
}


# --- key_pitch_classes ---

def test_c_major_pitch_classes():
    assert key_pitch_classes("C", "major") == {0, 2, 4, 5, 7, 9, 11}

def test_a_minor_pitch_classes():
    assert key_pitch_classes("A", "minor") == {9, 11, 0, 2, 4, 5, 7}

def test_f_sharp_major():
    pcs = key_pitch_classes("F#", "major")
    assert 6 in pcs  # F# itself must be in its own scale


# --- total_beats ---

def test_total_beats_single_section():
    assert total_beats(BLUEPRINT) == 16  # 4 bars * 4 beats

def test_total_beats_two_sections():
    bp = {**BLUEPRINT, "sections": [
        {"name": "verse", "bars": 4, "chords": ["C"] * 4},
        {"name": "chorus", "bars": 4, "chords": ["F"] * 4},
    ]}
    assert total_beats(bp) == 32


# --- validate_note_event ---

def test_valid_note_event():
    assert validate_note_event({"pitch": 60, "start_beat": 0, "duration": 1.0, "velocity": 90}) == []

def test_missing_duration():
    errs = validate_note_event({"pitch": 60, "start_beat": 0, "velocity": 90})
    assert any("duration" in e for e in errs)

def test_pitch_too_high():
    errs = validate_note_event({"pitch": 128, "start_beat": 0, "duration": 1.0, "velocity": 90})
    assert any("pitch" in e for e in errs)

def test_velocity_zero():
    errs = validate_note_event({"pitch": 60, "start_beat": 0, "duration": 1.0, "velocity": 0})
    assert any("velocity" in e for e in errs)

def test_negative_duration():
    errs = validate_note_event({"pitch": 60, "start_beat": 0, "duration": -1.0, "velocity": 90})
    assert any("duration" in e for e in errs)

def test_negative_start_beat():
    errs = validate_note_event({"pitch": 60, "start_beat": -1, "duration": 1.0, "velocity": 90})
    assert any("start_beat" in e for e in errs)


# --- validate_notes_in_range ---

def test_bass_in_range():
    notes = [{"pitch": 40, "start_beat": 0, "duration": 1, "velocity": 80}]
    assert validate_notes_in_range("bass", notes) == []

def test_bass_too_low():
    notes = [{"pitch": 10, "start_beat": 0, "duration": 1, "velocity": 80}]
    assert len(validate_notes_in_range("bass", notes)) == 1

def test_unknown_instrument_no_range_error():
    notes = [{"pitch": 10, "start_beat": 0, "duration": 1, "velocity": 80}]
    assert validate_notes_in_range("theremin", notes) == []


# --- validate_notes_in_key ---

def test_note_in_c_major():
    notes = [{"pitch": 60, "start_beat": 0, "duration": 1, "velocity": 80}]  # C4
    assert validate_notes_in_key("melody", notes, "C", "major") == []

def test_note_out_of_c_major():
    notes = [{"pitch": 61, "start_beat": 0, "duration": 1, "velocity": 80}]  # C#4
    assert len(validate_notes_in_key("melody", notes, "C", "major")) == 1

def test_drums_exempt_from_key():
    notes = [{"pitch": 36, "start_beat": 0, "duration": 0.25, "velocity": 100}]
    assert validate_notes_in_key("drums", notes, "C", "major") == []

def test_octave_equivalence():
    # C5 (72) should also be valid in C major
    notes = [{"pitch": 72, "start_beat": 0, "duration": 1, "velocity": 80}]
    assert validate_notes_in_key("melody", notes, "C", "major") == []


# --- validate_bar_lengths ---

def test_note_within_bounds():
    notes = [{"pitch": 60, "start_beat": 0, "duration": 4, "velocity": 80}]
    assert validate_bar_lengths("melody", notes, 16) == []

def test_note_beyond_song():
    notes = [{"pitch": 60, "start_beat": 15, "duration": 2, "velocity": 80}]
    assert len(validate_bar_lengths("melody", notes, 16)) == 1

def test_note_exactly_at_boundary():
    notes = [{"pitch": 60, "start_beat": 12, "duration": 4, "velocity": 80}]
    assert validate_bar_lengths("melody", notes, 16) == []


# --- validate_no_overlaps ---

def test_no_overlap_sequential():
    notes = [
        {"pitch": 60, "start_beat": 0, "duration": 1, "velocity": 80},
        {"pitch": 60, "start_beat": 1, "duration": 1, "velocity": 80},
    ]
    assert validate_no_overlaps("melody", notes) == []

def test_overlap_detected():
    notes = [
        {"pitch": 60, "start_beat": 0, "duration": 2, "velocity": 80},
        {"pitch": 60, "start_beat": 1, "duration": 1, "velocity": 80},
    ]
    assert len(validate_no_overlaps("melody", notes)) == 1

def test_different_pitches_no_overlap_error():
    notes = [
        {"pitch": 60, "start_beat": 0, "duration": 2, "velocity": 80},
        {"pitch": 64, "start_beat": 1, "duration": 1, "velocity": 80},
    ]
    assert validate_no_overlaps("melody", notes) == []

def test_drums_exempt_from_overlap():
    notes = [
        {"pitch": 36, "start_beat": 0,   "duration": 1, "velocity": 100},
        {"pitch": 36, "start_beat": 0.5, "duration": 1, "velocity": 100},
    ]
    assert validate_no_overlaps("drums", notes) == []


# --- validate_blueprint ---

def test_valid_blueprint():
    assert validate_blueprint(BLUEPRINT) == []

def test_blueprint_missing_key_field():
    bp = {k: v for k, v in BLUEPRINT.items() if k != "key"}
    assert any("key" in e for e in validate_blueprint(bp))

def test_blueprint_unknown_key():
    bp = {**BLUEPRINT, "key": "H"}
    assert any("Unknown key" in e for e in validate_blueprint(bp))

def test_blueprint_unknown_mode():
    bp = {**BLUEPRINT, "mode": "dorian"}
    assert any("Unknown mode" in e for e in validate_blueprint(bp))

def test_blueprint_chord_count_mismatch():
    bp = {**BLUEPRINT, "sections": [{"name": "verse", "bars": 4, "chords": ["C", "Am"]}]}
    errs = validate_blueprint(bp)
    assert len(errs) >= 1


# --- validate_part ---

def test_validate_part_clean():
    notes = [
        {"pitch": 60, "start_beat": 0, "duration": 1, "velocity": 80},  # C4
        {"pitch": 64, "start_beat": 1, "duration": 1, "velocity": 80},  # E4
    ]
    assert validate_part("melody", notes, BLUEPRINT) == []

def test_validate_part_out_of_key():
    notes = [{"pitch": 61, "start_beat": 0, "duration": 1, "velocity": 80}]  # C#
    assert len(validate_part("melody", notes, BLUEPRINT)) >= 1

def test_validate_part_drums_clean():
    notes = [
        {"pitch": 36, "start_beat": 0,   "duration": 0.25, "velocity": 100},
        {"pitch": 38, "start_beat": 1,   "duration": 0.25, "velocity": 80},
        {"pitch": 42, "start_beat": 0.5, "duration": 0.25, "velocity": 60},
    ]
    assert validate_part("drums", notes, BLUEPRINT) == []
