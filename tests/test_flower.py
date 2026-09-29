import json
from types import SimpleNamespace

import pytest

pytest.importorskip("flwr")
from flwr.app import RecordDict
from pendant_flower.agent_app import app


@pytest.mark.parametrize("mode", ["pipeline", "autonomous"])
def test_flower_app_offline_artifacts_and_events(tmp_path, mode):
    events = []
    agent = SimpleNamespace(prompt="upbeat funk, 110 BPM", events=SimpleNamespace(emit=events.append))
    context = SimpleNamespace(run_config={"provider": "offline", "mode": mode, "bars": 8,
                                          "output-dir": str(tmp_path)}, state=RecordDict())
    app(agent, context)
    saved = context.state["pendant.latest"]
    assert saved["song.mid"].startswith(b"MThd")
    assert json.loads(saved["song.json"])["blueprint"]["tempo"] == 110
    assert any(e["type"] == "response.output_text.delta" for e in events)
    assert "song.mid" in events[-1]["delta"]
    assert json.loads(saved["report.json"])["api_calls"] <= 60
    first = saved["output_dir"]
    app(agent, context)
    assert context.state["pendant.latest"]["output_dir"] != first
