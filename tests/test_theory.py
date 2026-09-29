import pytest

from core.theory import chord_pitch_classes, diatonic_chords, note_name, parse_chord, uses_flats
from agents.offline import degree_chord


def test_note_names():
    assert note_name(60) == "C4"
    assert note_name(70, flats=True) == "Bb4"


def test_parse_chords():
    assert chord_pitch_classes("Am7") == {9, 0, 4, 7}
    assert chord_pitch_classes("G/B") == {7, 11, 2}
    assert parse_chord("F#m7b5")[0] == 6
    with pytest.raises(ValueError):
        parse_chord("Hmaj")


def test_diatonic_chords():
    assert diatonic_chords("C", "major") == ["C", "Dm", "Em", "F", "G", "Am", "Bdim"]
    assert diatonic_chords("A", "minor") == ["Am", "Bdim", "C", "Dm", "Em", "F", "G"]
    assert degree_chord("C", "major", 5, True) == "G7"
    assert degree_chord("F", "major", 4, True) == "Bbmaj7"


def test_flat_keys():
    assert uses_flats("F", "major") and uses_flats("D", "minor")
    assert not uses_flats("A", "minor") and not uses_flats("G", "major")
