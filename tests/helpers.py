"""Shared test doubles. Nothing here talks to a real model."""

import json
from types import SimpleNamespace

from core.config import Settings
from core.llm import CallBudget, OfflineProvider

BLUEPRINT = {
    "title": "Test", "style": "lo-fi", "key": "C", "mode": "major", "tempo": 90,
    "time_signature": [4, 4],
    "sections": [
        {"name": "verse", "bars": 2, "chords": ["C", "Am"], "energy": 0.5},
        {"name": "chorus", "bars": 2, "chords": ["F", "G"], "energy": 0.9},
    ],
    "instruments": ["drums", "bass", "chords", "melody"],
}


def note(pitch, start, dur=1.0, vel=80):
    return {"pitch": pitch, "start_beat": start, "duration": dur, "velocity": vel}


class ScriptedLLM:
    """Plays back scripted answers per agent; anything unscripted goes to the offline band."""

    name = "scripted"

    def __init__(self, script=None, settings=None, max_calls=100):
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.budget = CallBudget(max_calls)
        self.offline = OfflineProvider(settings or Settings(provider="offline"), self.budget)
        self.calls = []

    def generate(self, agent, system, messages, schema_name, schema, context=None, tools=None,
                 max_tool_rounds=3):
        self.calls.append({"agent": agent, "schema": schema_name,
                           "messages": [dict(m) for m in messages], "tools": tools})
        queue = self.script.get(agent) or self.script.get(f"{agent}:{schema_name}")
        if queue:
            self.budget.spend(agent)
            answer = queue.pop(0)
            if tools and "check_my_part" in tools:
                self.calls[-1]["tool_result"] = tools["check_my_part"][2](answer)
            return json.loads(json.dumps(answer))
        return self.offline.generate(agent, system, messages, schema_name, schema, context, tools)


def openai_reply(content=None, tool_calls=None, refusal=None, finish_reason="stop"):
    message = SimpleNamespace(content=content, tool_calls=tool_calls, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


def tool_call(call_id, name, args):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeOpenAI:
    """Stands in for openai.OpenAI(): records requests, returns queued replies."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=str)))
        return self.replies.pop(0)
