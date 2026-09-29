# Optional Flower 1.39 integration

Pendant runs as **one AgentApp**, with the composer and instrument agents called
inside it. It does not distribute musicians across SuperNodes. Flower provides
Grid messaging through SuperLink, but this application does not need it.

## Install and run offline

Activate the project's virtual environment first (Flower launches other executables
from PATH), then run:

```bash
pip install -r requirements-flower.txt
flwr build
flwr chat
```

In Flower Chat:

```text
/load .
upbeat funk, 110 BPM
```

Flower's default local connection starts a local SuperLink. No hosted account or model
key is needed for Pendant's default `provider = "offline"`. Flower may separately try
to generate a conversation title; failures there do not mean music generation failed.

Before loading the app, edit `[tool.flwr.app.config]` in `pyproject.toml`:

```toml
provider = "offline"
mode = "autonomous"
bars = 8
output-dir = "/absolute/path/to/your/pendant/outputs/flower"
```

Keep `agent.input` empty for Chat prompts. Reload with `/load .` after changing the code
or configuration. Do not use `flwr run` for this AgentApp on 1.39: that command omits
`user_prompt`, which SuperLink requires even if `agent.input` is configured.

## Use your OpenAI account through a local SuperLink

Set `provider = "openai"` in the app configuration. In a terminal with the venv active:

```bash
export FLWR_MODEL_API_ENDPOINT=https://api.openai.com/v1/responses
export FLWR_MODEL_API_KEY="$OPENAI_API_KEY"
flower-superlink --insecure --host 127.0.0.1 --port 8000 --fleet-api-address 127.0.0.1:9092
```

This loopback server is for local development. Add this connection to Flower's
`config.toml` under its home directory (`FLWR_HOME`, normally `~/.flwr`):

```toml
[superlink.pendant]
address = "127.0.0.1:8000"
insecure = true
```

In another activated terminal:

```bash
FLWR_CHAT_SUPERLINK=pendant flwr chat
```

Then `/load .` and enter your music prompt. The AgentApp uses
`FLWR_RUNTIME_BASE_URL` and `FLWR_RUNTIME_API_KEY` injected by Flower. Your actual
OpenAI key stays with SuperLink. `model` selects the shared model; environment variables
`PENDANT_MODEL_<AGENT>` can override individual agents on a local runtime.

Flower 1.39's proxy rejects `store` and `include`. Pendant omits those fields only
through Flower, so the upstream provider's storage default applies. Direct OpenAI
Responses requests use `store=false` and request encrypted reasoning items for
stateless tool continuation. Both paths resend tool outputs and response items,
without depending on `previous_response_id`.

The cap counts **Pendant requests**, including tool continuations and validation
retries. Flower's separate title-generation request is outside Pendant's budget.

## Outputs and limitations

Each run has a unique subdirectory with `song.mid`, `song.json`, and `report.json`.
Set an absolute `output-dir` on the machine running the AgentApp; a path printed by a
remote server is not a download link on your laptop. Optional WAV output requires
FluidSynth and a SoundFont installed on that machine.

The latest MIDI bytes, song JSON and report are also stored in
`context.state["pendant.latest"]`. Progress is emitted as summary events and the final
file location as assistant text. A downloadable Flower Chat attachment or `flwr pull`
workflow for AgentApp files is **not implemented or claimed**.

## Verified integration check

```bash
python scripts/flower_smoke.py
```

This uses the installed Flower 1.39 Control API, the same `StartRun.user_prompt` path as
Chat, a real SuperLink, and a loopback mock upstream. It needs no API key. It verifies
transport and orchestration, not real OpenAI account access or musical quality.

References used alongside the installed 1.39.0 source:
- https://flower.ai/docs/agent/explanations/agentapp-runtime.html
- https://flower.ai/docs/agent/tutorials/write-your-first-agentapp.html
- https://flower.ai/docs/agent/how-to-guides/use-openai-sdk.html
