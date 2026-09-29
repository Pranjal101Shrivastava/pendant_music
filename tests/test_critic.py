"""The critic on deliberately bad songs: it has to catch real problems."""

from agents import critic
from agents.offline import compose, critique, play
from core.analysis import analyze
from core.config import Settings
from core.theory import chord_root, key_pitch_classes
from core.timeline import bar_map
from tests.helpers import BLUEPRINT, ScriptedLLM, note


def good_song(prompt="upbeat pop, 100 BPM", bars=8):
    bp = compose(prompt, bars, seed=1)
    parts = {}
    for role in ("drums", "bass", "chords", "melody"):
        parts[role] = play(role, bp, parts, 1, 0)
    return bp, parts


def flagged(bp, parts):
    return {i["agent"] for i in critique(bp, parts)["issues"]}


def test_good_song_is_accepted():
    bp, parts = good_song()
    report = critique(bp, parts)
    assert report["verdict"] == "accept" and analyze(bp, parts)["overall"] >= 4


def test_catches_bass_not_locked_to_kick():
    bp, parts = good_song()
    parts["bass"] = [dict(n, start_beat=n["start_beat"] + 0.75) for n in parts["bass"]
                     if n["start_beat"] % 4 == 0]
    assert "bass" in flagged(bp, parts)


def test_catches_melody_off_the_chords():
    bp, parts = good_song()
    # the scale step above each chord root is never a chord tone
    scale = sorted(key_pitch_classes(bp["key"], bp["mode"]))
    wrong = []
    for b in bar_map(bp):
        root = chord_root(b["chord"])
        step = scale[(scale.index(root) + 1) % 7]
        wrong += [note(60 + step, b["start_beat"] + k, 1) for k in range(4)]
    parts["melody"] = wrong
    assert "melody" in flagged(bp, parts)


def test_catches_a_melody_stuck_on_one_bar():
    bp, parts = good_song()
    parts["melody"] = [note(72, b * 4, 1) for b in range(8)] + [note(76, b * 4 + 1, 1) for b in range(8)]
    assert analyze(bp, parts)["details"]["melody_distinct_bars"] < 0.35
    assert "melody" in flagged(bp, parts)


def test_catches_missing_beat_and_chords_over_the_melody():
    bp, parts = good_song()
    parts["drums"] = [note(49, b * 4, 0.25) for b in range(8)]  # only crashes
    parts["chords"] = [note(p, b * 4, 4) for b in range(8) for p in (84, 88, 91)]
    assert {"drums", "chords"} <= flagged(bp, parts)


def test_report_limits_are_enforced():
    raw = {"verdict": "revise", "scores": {"groove": 9, "harmonic_fit": 0, "variation": 3, "balance": 3},
           "summary": "", "issues": [
               {"agent": "melody", "first_bar": 3, "last_bar": 99, "problem": "p", "fix": "f"},
               {"agent": "theremin", "first_bar": 1, "last_bar": 1, "problem": "p", "fix": "f"},
               {"agent": "bass", "first_bar": 1, "last_bar": 1, "problem": "p", "fix": "f"},
               {"agent": "drums", "first_bar": 1, "last_bar": 1, "problem": "p", "fix": "f"},
               {"agent": "chords", "first_bar": 1, "last_bar": 1, "problem": "p", "fix": "f"}]}
    parts = {r: [] for r in ("drums", "bass", "chords", "melody")}
    report = critic.clean_report(raw, BLUEPRINT, parts, max_issues=3)
    assert len(report["issues"]) == 3 and report["issues"][0]["last_bar"] == 4
    assert all(i["agent"] != "theremin" for i in report["issues"])
    assert report["scores"]["groove"] == 5 and report["scores"]["harmonic_fit"] == 1


def test_llm_critic_gets_the_measurements():
    bp, parts = good_song()
    llm = ScriptedLLM({"critic": [{"verdict": "accept", "summary": "fine", "issues": [],
                                   "scores": {"groove": 4, "harmonic_fit": 4, "variation": 4, "balance": 4}}]})
    report = critic.review(llm, Settings(provider="offline"), bp, parts, 1, lambda m: None)
    assert report["score"] == 4
    assert "Measurements from code" in llm.calls[0]["messages"][0]["content"]
