# Pendant: multi-agent music generation

A band of AI agents writes a song together and outputs a MIDI file. A **composer**
writes the blueprint (key, tempo, sections, one chord per bar). **Drums → bass → chords →
melody** each write their own part, hearing the parts written before theirs. A plain-code
**validator** checks every part, and a bounded **critic** loop asks the responsible agents
to fix specific bars.

The full design is in [`music-agents-prompt.md`](music-agents-prompt.md).

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt

python pipeline.py "sad lo-fi, 80 BPM"          # -> outputs/sad-lo-fi-80-bpm/song.mid
python pipeline.py --all                        # the 4 test prompts in prompts.json
python -m pytest                                # no paid model calls
```

**No API key? It still works.** Without `OPENAI_API_KEY`, every agent is played by a
rule-based stand-in (`agents/offline.py`), so the whole pipeline (validator, critic loop,
MIDI, audio) runs and can be tested for free. Those parts are also a baseline to compare
model output against.

**With OpenAI:** set the key in your shell (never in a file in the repo):

```bash
export OPENAI_API_KEY=...            # macOS / Linux
$env:OPENAI_API_KEY="..."            # Windows PowerShell
python pipeline.py "upbeat funk, 110 BPM" --provider openai
```

All agents default to `gpt-5-mini`. `PENDANT_MODEL` changes the shared default;
`PENDANT_MODEL_<AGENT>` overrides one agent (see `.env.example`). The default transport
is the OpenAI Responses API; `PENDANT_API=chat` selects the legacy Chat Completions
transport. No real key is included. API-key-backed musical quality has not been tested.
SDK automatic retries are disabled so each attempted request counts toward the budget.

## Command line

| Option | What it does |
|---|---|
| `--bars N` | Song length (default 16: intro, verse, chorus, outro) |
| `--provider auto\|openai\|offline` | `auto` uses OpenAI when `OPENAI_API_KEY` is set |
| `--mode pipeline\|autonomous` | `autonomous` turns on the version-2 features (phase 7) |
| `--critic-rounds N` | 0 turns the critic off; default 2 (the plan's max) |
| `--max-calls N` | Global cap on model calls per run (default 60) |
| `--audio` | Also render `song.wav` with FluidSynth (phase 8) |
| `--seed N` | Varies the offline musicians |

Each run writes `outputs/<prompt>/song.mid`, `song.json` (blueprint + notes) and
`report.json` (call counts, retries, repairs, critic rounds).

## How it's built (phases)

| Phase | What | Where |
|---|---|---|
| 0 | venv, dependencies, skeleton | `requirements.txt`, `conftest.py` |
| 1 | Note events → `.mid` (tracks per role, GM programs, drums on channel 10, tempo + time signature) | `core/midi_writer.py`, `examples/hand_written_song.json` |
| 2 | Schemas + validator: range, key, bar lengths, overlaps, one-note-at-a-time bass/melody, 16th grid for drums, chords must fit the key, instruments per section. Errors name the bar and beat. | `core/schemas.py`, `core/validator.py`, `core/theory.py` |
| 3 | Composer + melody agents, shared model helper, per-agent model settings | `agents/composer.py`, `agents/melody.py`, `core/llm.py`, `core/config.py` |
| 4 | Drums (genre templates) and bass (locked to the kick); later agents see earlier parts | `agents/drums.py`, `agents/bass.py` |
| 5 | Chords, validator retry loop (errors go back to the same agent, 2 retries, then code repairs), full song structure | `agents/chords.py`, `agents/base.py` |
| 6 | Critic: fixed rubric (groove, harmonic fit, variation, balance) backed by measurements, max 3 issues and 2 rounds, only flagged agents rewrite only flagged bars, the best version is kept, global call cap | `agents/critic.py`, `core/analysis.py`, `pipeline.py` |
| 7a | Agents call a `check_my_part` tool before answering | `agents/base.py` |
| 7b | Composer as orchestrator: picks which instruments play and in what order | `agents/composer.py` |
| 7c | Agents send feedback; the composer may revise the blueprint (at most once) | `agents/composer.py`, `pipeline.py` |
| 8 | Optional Flower AgentApp (`pendant_flower/`) and audio via a portable FluidSynth in `tools/fluidsynth/` + a `.sf2` in `soundfonts/` (both git-ignored) | `core/audio.py` |

Version-1 pieces (schemas, validator, MIDI writer, blueprint format) are unchanged by
version 2; phase 7 only adds switches in `core/config.py`.

## Differences from the plan

- **OpenAI instead of Claude.** One provider class in `core/llm.py` uses structured
  outputs (strict JSON schema, `core/json_schemas.py`) instead of forced tool calls.
  Adding another provider means adding one class with the same `generate()` method.
- **Offline provider added**, so everything runs and is tested without a key.
- **Flower is optional.** One AgentApp wraps the whole band; see [Flower setup](docs/flower.md).
  The standalone pipeline needs no Flower server.

## Layout

```
pipeline.py            entry point / CLI
agents/                composer, drums, bass, chords, melody, critic, base (shared loop), offline stand-ins
core/                  schemas, validator, theory, timeline, midi_writer, llm, config,
                       json_schemas, describe (text views for prompts), analysis (critic metrics), audio
examples/              hand_written_song.json (phase 1)
tests/                 pytest, no model calls (fake OpenAI client + scripted agents)
prompts.json           fixed test prompts to compare versions by ear
```

## Audio rendering

The uploaded WAV was an earlier output from Claude, not proof of this environment's
renderer. To render your own MIDI, put a FluidSynth executable under
`tools/fluidsynth/` and a licensed General MIDI `.sf2` under `soundfonts/`, or set
`FLUIDSYNTH` and `PENDANT_SOUNDFONT` to their paths, then add `--audio`.
These binaries/assets are not bundled. A missing renderer leaves the MIDI intact
and prints a clear message. Install instructions: https://www.fluidsynth.org/download/

## Verification

```bash
python -m pytest -q
# Optional full Flower transport check (Linux/macOS, no model key needed):
pip install -r requirements-flower.txt
python scripts/flower_smoke.py
```

The smoke check starts a real local SuperLink and a mock Responses server, runs offline
and mock-backed autonomous songs, and checks four `check_my_part` round trips,
structured outputs, per-agent model selection, and generated MIDI. Temporary runtime
files are removed when it finishes. It does not assess a real model's musical quality.

Python 3.11+ is required. Flower is constrained to 1.39.x because AgentApp APIs are new.
The repository had no license; `LICENSE` retains all rights rather than choosing an
open-source license on the owner's behalf (Flower bundle format 1 requires this file).
