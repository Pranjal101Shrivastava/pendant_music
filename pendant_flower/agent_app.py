"""Run the whole Pendant band inside one Flower 1.39 AgentApp."""
import os
from pathlib import Path
from uuid import uuid4

from flwr.agentapp import AgentApp, AgentSession
from flwr.app import ConfigRecord, Context

from core.config import Settings
from core.llm import CallBudget, OfflineProvider, OpenAIResponsesProvider
from pipeline import run

app = AgentApp()


def execute(agent, context):
    config = context.run_config
    prompt = config.get("agent.input") or agent.prompt
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Supply a non-empty song prompt through Flower Chat or agent.input")
    provider = config.get("provider", "offline")
    mode = config.get("mode", "pipeline")
    if provider not in {"offline", "openai"}:
        raise ValueError("Flower provider must be offline or openai")
    if mode not in {"pipeline", "autonomous"}:
        raise ValueError("mode must be pipeline or autonomous")
    autonomous = mode == "autonomous"
    settings = Settings.from_env(
        provider=provider, api="responses", default_model=config.get("model", "gpt-5-mini"),
        max_api_calls=config.get("max-calls", 60), critic_rounds=config.get("critic-rounds", 2),
        self_check=autonomous, orchestrate=autonomous, feedback=autonomous,
    )
    settings.validate()
    budget = CallBudget(settings.max_api_calls)
    if provider == "offline":
        llm = OfflineProvider(settings, budget)
    else:
        from openai import OpenAI
        endpoint = os.environ.get("FLWR_RUNTIME_BASE_URL")
        key = os.environ.get("FLWR_RUNTIME_API_KEY")
        if not endpoint or not key:
            raise RuntimeError("Flower runtime credentials are missing. Launch this app through flwr.")
        client = OpenAI(base_url=endpoint, api_key=key, max_retries=0, timeout=180.0)
        llm = OpenAIResponsesProvider(settings, budget, client=client, flower_runtime=True)

    # Each run gets its own directory so a repeated prompt cannot overwrite a song.
    output = Path(config.get("output-dir", "outputs/flower")).expanduser().resolve() / uuid4().hex
    def progress(message):
        print(message)
        agent.events.emit({"type": "response.reasoning_summary_text.delta", "delta": message + "\n"})

    result = run(prompt.strip(), settings, bars=config.get("bars", 16), out_root=str(output),
                 llm=llm, audio=config.get("audio", False), log=progress)
    out = Path(result["out_dir"])
    # Preserve small artifacts in the run-series context as well as the local files.
    # This is not a claim that Flower Chat provides file-download attachments.
    context.state["pendant.latest"] = ConfigRecord({
        "song.mid": (out / "song.mid").read_bytes(),
        "song.json": (out / "song.json").read_text(),
        "report.json": (out / "report.json").read_text(),
        "output_dir": str(out),
    })
    bp = result["blueprint"]
    summary = (f"Created {bp.get('title', 'song')}: {bp['key']} {bp['mode']}, "
               f"{bp['tempo']} BPM, {result['report']['bars']} bars.\n"
               f"Files on the machine running the AgentApp: {out}\n"
               "song.mid, song.json, report.json. Import song.mid into your DAW.\n"
               f"Pendant model/provider calls: {budget.used}.\n")
    agent.events.emit({"type": "response.output_text.delta", "delta": summary})
    print(summary)
    return result


@app.main()
def main(agent: AgentSession, context: Context) -> None:
    execute(agent, context)
