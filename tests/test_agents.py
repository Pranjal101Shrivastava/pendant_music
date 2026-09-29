import copy

from agents import composer
from agents.bass import AGENT as BASS
from agents.melody import AGENT as MELODY
from core.config import Settings
from core.validator import validate_blueprint, validate_part
from tests.helpers import BLUEPRINT, ScriptedLLM, note

SETTINGS = Settings(provider="offline")
QUIET = lambda msg: None


def test_validator_errors_go_back_to_the_same_agent():
    bad = {"notes": [note(61, 0, 4)] + [note(60, b * 4, 4) for b in (1, 2, 3)]}   # C# is not in C major
    good = {"notes": [note(60, b * 4, 4) for b in range(4)]}
    llm = ScriptedLLM({"melody": [bad, good]})
    result = MELODY.write(llm, SETTINGS, BLUEPRINT, {}, QUIET)
    assert result.attempts == 2 and result.notes == good["notes"]
    retry = llm.calls[-1]["messages"]
    assert retry[-1]["role"] == "user" and "C#4" in retry[-1]["content"]
    assert retry[-2]["role"] == "assistant"


def test_after_retries_code_repairs_the_best_attempt():
    bad = {"notes": [note(61, 0, 4), note(60, 4, 8), note(64, 6), note(67, 12, 4)]}
    llm = ScriptedLLM({"melody": [bad, bad, bad]})
    result = MELODY.write(llm, SETTINGS, BLUEPRINT, {}, QUIET)
    assert result.attempts == 3 and result.repaired
    assert validate_part("melody", result.notes, BLUEPRINT) == []


def test_request_shows_earlier_parts():
    llm = ScriptedLLM()
    drums = [note(36, 0, 0.25), note(38, 1, 0.25)]
    BASS.write(llm, SETTINGS, BLUEPRINT, {"drums": drums}, QUIET)
    request = llm.calls[0]["messages"][0]["content"]
    assert "DRUMS part" in request and "kick 1" in request and "Notes in the key" in request


def test_revise_rewrites_only_flagged_bars():
    current = [note(60, b * 4, 4) for b in range(4)]
    llm = ScriptedLLM({"melody": [{"notes": [note(64, 4, 2), note(67, 6, 2), note(72, 0, 4)]}]})
    issue = {"agent": "melody", "first_bar": 2, "last_bar": 2, "problem": "flat", "fix": "move"}
    result = MELODY.revise(llm, SETTINGS, BLUEPRINT, {"melody": current}, issue, 1, QUIET)
    assert [n["pitch"] for n in result.notes] == [60, 64, 67, 60, 60]  # the bar-1 note it sent is ignored
    assert "bars 2-2" in llm.calls[0]["messages"][0]["content"]


def test_self_check_tool_is_offered_in_version_2():
    llm = ScriptedLLM({"melody": [{"notes": [note(61, 0)]}, {"notes": [note(60, b * 4, 4) for b in range(4)]}]})
    MELODY.write(llm, Settings(provider="offline", self_check=True), BLUEPRINT, {}, QUIET)
    assert "check_my_part" in llm.calls[0]["tools"]
    assert "C#4" in llm.calls[0]["tool_result"]


def test_feedback_is_collected_in_version_2():
    reply = {"notes": [note(60, b * 4, 4) for b in range(4)], "feedback_to_composer": "tempo is too fast"}
    llm = ScriptedLLM({"melody": [reply]})
    result = MELODY.write(llm, Settings(provider="offline", feedback=True), BLUEPRINT, {}, QUIET)
    assert result.feedback == "tempo is too fast" and llm.calls[0]["schema"] == "part_with_feedback"


def test_composer_retries_when_bars_dont_add_up():
    short = copy.deepcopy(BLUEPRINT)
    llm = ScriptedLLM({"composer": [short, copy.deepcopy(BLUEPRINT)]})
    llm.script["composer"][1]["sections"].append({"name": "outro", "bars": 4, "chords": ["C", "F", "G", "C"],
                                                  "energy": 0.3, "instruments": ["chords"]})
    bp = composer.compose(llm, SETTINGS, "test", bars=8, log=QUIET)
    assert validate_blueprint(bp) == [] and sum(s["bars"] for s in bp["sections"]) == 8
    assert "8 bars" in llm.calls[1]["messages"][-1]["content"]


def test_orchestrator_can_leave_an_instrument_out():
    llm = ScriptedLLM({"composer": [{"order": ["drums", "chords", "melody"], "reason": "no bass"}]})
    order, bp = composer.choose_order(llm, SETTINGS, copy.deepcopy(BLUEPRINT), QUIET)
    assert order == ["drums", "chords", "melody"] and "bass" not in bp["instruments"]


def test_composer_revises_blueprint_on_feedback():
    slower = copy.deepcopy(BLUEPRINT)
    slower["tempo"] = 70
    llm = ScriptedLLM({"composer": [{"revise": True, "reason": "slower", "blueprint": slower}]})
    new = composer.consider_feedback(llm, SETTINGS, BLUEPRINT, {"melody": "too fast"}, QUIET)
    assert new["tempo"] == 70
    assert composer.consider_feedback(llm, SETTINGS, BLUEPRINT, {"melody": ""}, QUIET) is None
