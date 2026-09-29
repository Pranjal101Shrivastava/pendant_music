import json
import os

import pretty_midi
import pytest

import pipeline
from core.config import Settings
from core.validator import validate_blueprint, validate_part
from tests.helpers import ScriptedLLM

QUIET = lambda msg: None
PROMPTS = json.load(open(os.path.join(os.path.dirname(__file__), "..", "prompts.json")))


@pytest.mark.parametrize("prompt", PROMPTS)
def test_offline_run_writes_a_valid_song(prompt, tmp_path):
    result = pipeline.run(prompt, Settings(provider="offline"), bars=16, out_root=str(tmp_path), log=QUIET)
    bp = result["blueprint"]
    assert validate_blueprint(bp) == []
    for role, notes in result["parts"].items():
        assert validate_part(role, notes, bp) == [], role
    out = result["out_dir"]
    assert {"song.mid", "song.json", "report.json"} <= set(os.listdir(out))
    midi = pretty_midi.PrettyMIDI(os.path.join(out, "song.mid"))
    assert len(midi.instruments) == len(bp["instruments"])
    assert result["report"]["api_calls"] <= Settings().max_api_calls


def test_critic_loop_revises_then_keeps_the_best_version(tmp_path):
    def report(score, issues=()):
        return {"verdict": "revise" if issues else "accept", "summary": "",
                "scores": {k: score for k in ("groove", "harmonic_fit", "variation", "balance")},
                "issues": list(issues)}
    issue = {"agent": "melody", "first_bar": 5, "last_bar": 6, "problem": "dull", "fix": "vary"}
    llm = ScriptedLLM({"critic": [report(4, [issue]), report(3, [issue]), report(2)]})
    settings = Settings(provider="offline", critic_rounds=2)
    result = pipeline.run("sad lo-fi, 80 BPM", settings, bars=16, out_root=str(tmp_path), llm=llm, log=QUIET)
    rounds = result["report"]["critic"]
    assert [r["round"] for r in rounds] == [1, 2, 3]            # 2 revision rounds + final check
    revisions = [c for c in llm.calls if c["agent"] == "melody"][1:]
    assert len(revisions) == 2 and "bars 5-6" in revisions[0]["messages"][0]["content"]
    first_version = json.load(open(os.path.join(result["out_dir"], "song.json")))
    assert result["parts"]["melody"] == first_version["song"]["instruments"]["melody"]
    # round 1 scored best, so its (unrevised) melody is what got written


def test_call_cap_stops_the_critic_but_still_writes_a_song(tmp_path):
    llm = ScriptedLLM(max_calls=6)  # composer + 4 parts + 1 critic call
    result = pipeline.run("upbeat funk, 110 BPM", Settings(provider="offline"), bars=8,
                          out_root=str(tmp_path), llm=llm, log=QUIET)
    assert os.path.exists(os.path.join(result["out_dir"], "song.mid"))
    assert llm.budget.used == 6


def test_autonomous_mode_offline(tmp_path):
    settings = Settings(provider="offline", self_check=True, orchestrate=True, feedback=True)
    result = pipeline.run("dreamy ambient, 70 BPM", settings, bars=16, out_root=str(tmp_path), log=QUIET)
    assert result["report"]["order"] == ["drums", "bass", "chords", "melody"]
    assert result["report"]["calls_by_agent"]["composer"] == 2  # blueprint + running order


def test_cli(tmp_path):
    assert pipeline.main(["upbeat funk, 110 BPM", "--bars", "8", "--provider", "offline",
                          "--out", str(tmp_path)]) == 0
    assert os.path.exists(tmp_path / "upbeat-funk-110-bpm" / "song.mid")


def test_feedback_revision_adds_instrument(tmp_path, monkeypatch):
    import copy
    from tests.helpers import BLUEPRINT
    initial = copy.deepcopy(BLUEPRINT)
    initial['instruments'] = ['bass']
    for sec in initial['sections']:
        sec['instruments'] = ['bass']
    revised = copy.deepcopy(initial)
    revised['instruments'].append('melody')
    for sec in revised['sections']:
        sec['instruments'].append('melody')
    monkeypatch.setattr(pipeline.composer, 'compose', lambda *a: initial)
    monkeypatch.setattr(pipeline.composer, 'consider_feedback', lambda *a: revised)
    result = pipeline.run('test', Settings(provider='offline', feedback=True, critic_rounds=0),
                          bars=4, out_root=str(tmp_path), log=QUIET)
    assert set(result['parts']) == {'bass', 'melody'}
    assert result['parts']['melody']


@pytest.mark.parametrize('setting,value', [('critic_rounds', 3), ('max_retries', 4),
                                          ('max_api_calls', 0), ('max_blueprint_revisions', 2)])
def test_settings_enforce_bounds(setting, value, tmp_path):
    with pytest.raises(ValueError, match=setting):
        pipeline.run('test', Settings(**{setting: value}), out_root=str(tmp_path), log=QUIET)


def test_global_model_override_applies_to_all_agents(monkeypatch):
    monkeypatch.setenv('PENDANT_MODEL', 'selected-model')
    monkeypatch.delenv('PENDANT_MODEL_COMPOSER', raising=False)
    monkeypatch.delenv('PENDANT_MODEL_CRITIC', raising=False)
    settings = Settings.from_env()
    assert all(settings.model_for(role) == 'selected-model' for role in pipeline.INSTRUMENTS)
    assert settings.model_for('composer') == settings.model_for('critic') == 'selected-model'
