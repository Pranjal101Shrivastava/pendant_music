"""Model access for all agents: one generate() call that returns parsed JSON.

Providers share the same interface:
- OpenAIResponsesProvider: Responses API (default; also used through Flower).
- OpenAIProvider: legacy chat completions with a strict JSON schema (structured outputs).
  Reads OPENAI_API_KEY from the environment; the key is never passed around or stored.
- OfflineProvider: rule-based musicians (agents/offline.py), so the whole pipeline runs
  and can be tested without an API key.

Both count calls against one CallBudget (the plan's global cap per run).
"""

import json
import os
from typing import Callable, Dict, List, Optional, Tuple

from core.config import Settings

# name -> (description, JSON schema of the arguments, function(args) -> str)
Tool = Tuple[str, dict, Callable[[dict], str]]


class LLMError(RuntimeError):
    """The model call failed in a way retrying the same request won't fix."""


class LLMOutputError(LLMError):
    """The model answered, but not with usable JSON. Worth sending back to it."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


class BudgetExceeded(LLMError):
    pass


class CallBudget:
    def __init__(self, max_calls: int):
        self.max_calls = max_calls
        self.used = 0
        self.by_agent: Dict[str, int] = {}

    def spend(self, agent: str) -> None:
        if self.used >= self.max_calls:
            raise BudgetExceeded(f"global cap of {self.max_calls} model calls reached "
                                 f"(calls so far: {self.by_agent})")
        self.used += 1
        self.by_agent[agent] = self.by_agent.get(agent, 0) + 1


class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: Settings, budget: CallBudget, client=None):
        self.settings = settings
        self.budget = budget
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise LLMError("OPENAI_API_KEY is not set. Export it in your shell, or run with "
                               "--provider offline to use the built-in rule-based musicians.")
            from openai import OpenAI  # imported here so offline runs don't need the package

            client = OpenAI(max_retries=0, timeout=120.0)
        self.client = client

    def generate(self, agent: str, system: str, messages: List[dict], schema_name: str,
                 schema: dict, context: Optional[dict] = None,
                 tools: Optional[Dict[str, Tool]] = None, max_tool_rounds: int = 3) -> dict:
        convo = [{"role": "system", "content": system}, *messages]
        tool_specs = [
            {"type": "function", "function": {"name": name, "description": desc,
                                              "parameters": params, "strict": True}}
            for name, (desc, params, _) in (tools or {}).items()
        ]
        for round_ in range(max_tool_rounds + 1):
            self.budget.spend(agent)
            kwargs = {
                "model": self.settings.model_for(agent),
                "messages": convo,
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": schema_name, "schema": schema,
                                                    "strict": True}},
                "max_completion_tokens": self.settings.max_output_tokens,
            }
            if tool_specs:
                kwargs["tools"] = tool_specs
                # last round: no more tool calls, answer now
                kwargs["tool_choice"] = "none" if round_ == max_tool_rounds else "auto"
            if self.settings.reasoning_effort:
                kwargs["reasoning_effort"] = self.settings.reasoning_effort
            response = self.client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            message = choice.message
            if getattr(message, "refusal", None):
                raise LLMError(f"{agent}: the model refused: {message.refusal}")
            if message.tool_calls:
                convo.append({
                    "role": "assistant", "content": message.content,
                    "tool_calls": [{"id": tc.id, "type": "function",
                                    "function": {"name": tc.function.name,
                                                 "arguments": tc.function.arguments}}
                                   for tc in message.tool_calls],
                })
                for tc in message.tool_calls:
                    convo.append({"role": "tool", "tool_call_id": tc.id,
                                  "content": _run_tool(tools or {}, tc.function.name,
                                                       tc.function.arguments)})
                continue
            if choice.finish_reason == "length":
                raise LLMOutputError(f"{agent}: the answer was cut off at max_output_tokens "
                                     f"({self.settings.max_output_tokens})", message.content or "")
            try:
                return json.loads(message.content or "")
            except json.JSONDecodeError as e:
                raise LLMOutputError(f"{agent}: the answer was not valid JSON ({e})",
                                     message.content or "")
        raise LLMError(f"{agent}: no answer after {max_tool_rounds} tool rounds")



class OpenAIResponsesProvider(OpenAIProvider):
    """Stateless Responses API transport, including bounded self-check tool calls.

    Resend response output items (including reasoning items) with function results;
    this works through Flower without relying on previous_response_id storage.
    """

    def __init__(self, settings: Settings, budget: CallBudget, client=None, *, flower_runtime=False):
        super().__init__(settings, budget, client)
        self.flower_runtime = flower_runtime

    def generate(self, agent: str, system: str, messages: List[dict], schema_name: str,
                 schema: dict, context: Optional[dict] = None,
                 tools: Optional[Dict[str, Tool]] = None, max_tool_rounds: int = 3) -> dict:
        convo = list(messages)
        specs = [{"type": "function", "name": name, "description": desc,
                  "parameters": params, "strict": True}
                 for name, (desc, params, _) in (tools or {}).items()]
        for round_ in range(max_tool_rounds + 1):
            self.budget.spend(agent)
            kwargs = dict(model=self.settings.model_for(agent), instructions=system,
                          input=list(convo), store=False, include=["reasoning.encrypted_content"],
                          text={"format": {"type": "json_schema", "name": schema_name,
                                           "schema": schema, "strict": True}},
                          max_output_tokens=self.settings.max_output_tokens)
            if self.flower_runtime:
                # Flower 1.39 rejects store/include; upstream storage defaults apply.
                kwargs.pop("store")
                kwargs.pop("include")
            if specs:
                kwargs.update(tools=specs, tool_choice="none" if round_ == max_tool_rounds else "auto")
            if self.settings.reasoning_effort:
                kwargs["reasoning"] = {"effort": self.settings.reasoning_effort}
            response = self.client.responses.create(**kwargs)
            if response.status == "incomplete":
                raise LLMOutputError(f"{agent}: incomplete answer (possibly cut off at "
                                     f"max_output_tokens={self.settings.max_output_tokens})",
                                     response.output_text or "")
            if response.status != "completed":
                raise LLMError(f"{agent}: model response status {response.status}")
            for item in response.output:
                for content in getattr(item, "content", []) or []:
                    if getattr(content, "type", None) == "refusal":
                        raise LLMError(f"{agent}: the model refused: {content.refusal}")
            calls = [item for item in response.output if item.type == "function_call"]
            if calls:
                if round_ == max_tool_rounds:
                    raise LLMOutputError(f"{agent}: tool round limit reached without an answer")
                convo.extend(item.model_dump(exclude_none=True) for item in response.output)
                for call in calls:
                    convo.append({"type": "function_call_output", "call_id": call.call_id,
                                  "output": _run_tool(tools or {}, call.name, call.arguments)})
                continue
            try:
                result = json.loads(response.output_text or "")
            except json.JSONDecodeError as e:
                raise LLMOutputError(f"{agent}: the answer was not valid JSON ({e})",
                                     response.output_text or "") from e
            if not isinstance(result, dict):
                raise LLMOutputError(f"{agent}: answer must be a JSON object", response.output_text)
            return result
        raise LLMError(f"{agent}: no answer after {max_tool_rounds} tool rounds")


def _run_tool(tools: Dict[str, Tool], name: str, arguments: str) -> str:
    if name not in tools:
        return f"error: unknown tool {name}"
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError as e:
        return f"error: arguments were not valid JSON ({e})"
    if not isinstance(args, dict):
        return "error: tool arguments must be a JSON object"
    try:
        return tools[name][2](args)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return f"error: invalid tool arguments ({exc})"


class OfflineProvider:
    """Rule-based stand-ins for every agent. Same interface, no network, no key."""

    name = "offline"

    def __init__(self, settings: Settings, budget: CallBudget):
        self.settings = settings
        self.budget = budget

    def generate(self, agent: str, system: str, messages: List[dict], schema_name: str,
                 schema: dict, context: Optional[dict] = None,
                 tools: Optional[Dict[str, Tool]] = None, max_tool_rounds: int = 3) -> dict:
        from agents import offline

        self.budget.spend(agent)
        attempt = sum(1 for m in messages if m["role"] == "user") - 1
        result = offline.respond(agent, schema_name, context or {}, attempt, self.settings.seed)
        if tools and "check_my_part" in tools:  # offline players check their own work too
            tools["check_my_part"][2]({"notes": result.get("notes", [])})
        return result


def make_provider(settings: Settings, budget: CallBudget, client=None):
    provider = settings.resolved_provider()
    if provider == "openai":
        settings.validate()
        cls = OpenAIResponsesProvider if settings.api == "responses" else OpenAIProvider
        return cls(settings, budget, client)
    if provider == "offline":
        return OfflineProvider(settings, budget)
    raise LLMError(f"unknown provider {provider!r}; use openai or offline")
