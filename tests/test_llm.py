import json

import pytest

from core.config import Settings
from core.json_schemas import PART
from core.llm import BudgetExceeded, CallBudget, LLMError, LLMOutputError, OpenAIProvider, make_provider
from tests.helpers import FakeOpenAI, openai_reply, tool_call

ASK = dict(agent="melody", system="sys", messages=[{"role": "user", "content": "hi"}],
           schema_name="part", schema=PART)


def provider(replies, **settings):
    client = FakeOpenAI(replies)
    return OpenAIProvider(Settings(provider="openai", **settings), CallBudget(10), client), client


def test_structured_output_request_and_parse():
    p, client = provider([openai_reply(json.dumps({"notes": []}))], reasoning_effort="low")
    assert p.generate(**ASK) == {"notes": []}
    req = client.requests[0]
    assert req["model"] == Settings().model_for("melody")
    assert req["response_format"]["json_schema"]["strict"] is True
    assert req["messages"][0] == {"role": "system", "content": "sys"}
    assert req["reasoning_effort"] == "low" and "tools" not in req


def test_per_agent_model_setting():
    p, client = provider([openai_reply("{}")], models={"melody": "my-model"})
    p.generate(**ASK)
    assert client.requests[0]["model"] == "my-model"


def test_refusal_and_bad_output():
    p, _ = provider([openai_reply(refusal="no")])
    with pytest.raises(LLMError, match="refused"):
        p.generate(**ASK)
    p, _ = provider([openai_reply("not json")])
    with pytest.raises(LLMOutputError):
        p.generate(**ASK)
    p, _ = provider([openai_reply('{"notes": [', finish_reason="length")])
    with pytest.raises(LLMOutputError, match="cut off"):
        p.generate(**ASK)


def test_tool_loop_runs_check_my_part_then_answers():
    seen = []
    tools = {"check_my_part": ("check", PART, lambda args: seen.append(args) or "OK")}
    p, client = provider([
        openai_reply(tool_calls=[tool_call("c1", "check_my_part", {"notes": []})]),
        openai_reply(json.dumps({"notes": []})),
    ])
    assert p.generate(**ASK, tools=tools) == {"notes": []}
    assert seen == [{"notes": []}]
    second = client.requests[1]
    assert second["messages"][-1] == {"role": "tool", "tool_call_id": "c1", "content": "OK"}
    assert second["tools"][0]["function"]["strict"] is True


def test_last_tool_round_forces_an_answer():
    tools = {"check_my_part": ("check", PART, lambda args: "OK")}
    calls = [openai_reply(tool_calls=[tool_call(f"c{i}", "check_my_part", {"notes": []})]) for i in range(2)]
    p, client = provider(calls + [openai_reply('{"notes": []}')])
    p.generate(**ASK, tools=tools, max_tool_rounds=2)
    assert client.requests[-1]["tool_choice"] == "none"


def test_global_call_cap():
    budget = CallBudget(1)
    budget.spend("composer")
    with pytest.raises(BudgetExceeded):
        budget.spend("drums")


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        make_provider(Settings(provider="openai"), CallBudget(5))
    assert make_provider(Settings(provider="auto"), CallBudget(5)).name == "offline"


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("PENDANT_MODEL_CRITIC", "critic-model")
    monkeypatch.setenv("PENDANT_MAX_API_CALLS", "7")
    s = Settings.from_env(critic_rounds=1)
    assert s.model_for("critic") == "critic-model" and s.max_api_calls == 7 and s.critic_rounds == 1
