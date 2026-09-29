"""Run settings. Everything can be overridden with environment variables.

The API key is never stored here or in any file: the OpenAI provider reads
OPENAI_API_KEY from the environment.

    PENDANT_PROVIDER        auto (default) | openai | offline
    PENDANT_MODEL           default model for every agent
    PENDANT_MODEL_<AGENT>   per-agent model, e.g. PENDANT_MODEL_COMPOSER
    PENDANT_MAX_API_CALLS   global cap on model calls per run
    PENDANT_MAX_RETRIES     validator retries per agent
    PENDANT_CRITIC_ROUNDS   critic rounds (0 disables the critic)
"""

import os
from dataclasses import dataclass, field
from typing import Dict

AGENTS = ["composer", "drums", "bass", "chords", "melody", "critic"]

# Placeholder model names - change them to the OpenAI models you want to use.
DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_MODELS = {}


@dataclass
class Settings:
    provider: str = "auto"
    api: str = "responses"         # responses | chat (legacy compatibility)
    models: Dict[str, str] = field(default_factory=dict)
    default_model: str = DEFAULT_MODEL
    max_retries: int = 2           # validator retries per agent (the plan says 2-3)
    max_api_calls: int = 60        # global cap per run
    critic_rounds: int = 2         # the plan's max
    max_issues: int = 3            # critic issues per round
    max_output_tokens: int = 16000
    reasoning_effort: str = ""     # e.g. "low" / "medium" for reasoning models; "" = model default
    seed: int = 0                  # offline musicians' randomness
    # Version 2 (phase 7) switches
    self_check: bool = False       # 7a: agents call check_my_part themselves
    orchestrate: bool = False      # 7b: composer picks which instruments play, in what order
    feedback: bool = False         # 7c: agents send notes back; composer may revise the blueprint
    max_blueprint_revisions: int = 1

    def model_for(self, agent: str) -> str:
        return self.models.get(agent) or self.default_model

    def resolved_provider(self) -> str:
        if self.provider != "auto":
            return self.provider
        return "openai" if os.environ.get("OPENAI_API_KEY") else "offline"

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        s = cls()
        env = os.environ
        s.api = env.get("PENDANT_API", s.api)
        s.provider = env.get("PENDANT_PROVIDER", s.provider)
        s.default_model = env.get("PENDANT_MODEL", s.default_model)
        for agent in AGENTS:
            value = env.get(f"PENDANT_MODEL_{agent.upper()}")
            if value:
                s.models[agent] = value
        s.max_api_calls = int(env.get("PENDANT_MAX_API_CALLS", s.max_api_calls))
        s.max_retries = int(env.get("PENDANT_MAX_RETRIES", s.max_retries))
        s.critic_rounds = int(env.get("PENDANT_CRITIC_ROUNDS", s.critic_rounds))
        s.reasoning_effort = env.get("PENDANT_REASONING_EFFORT", s.reasoning_effort)
        for key, value in overrides.items():
            if value is not None:
                setattr(s, key, value)
        return s

    def validate(self) -> None:
        if self.provider not in {"auto", "openai", "offline"}:
            raise ValueError("provider must be auto, openai or offline")
        if self.api not in {"responses", "chat"}:
            raise ValueError("PENDANT_API must be responses or chat")
        for name, lo, hi in (("max_retries", 0, 3), ("critic_rounds", 0, 2),
                             ("max_issues", 1, 3), ("max_blueprint_revisions", 0, 1)):
            value = getattr(self, name)
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError(f"{name} must be an integer from {lo} to {hi}")
        for name in ("max_api_calls", "max_output_tokens"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
