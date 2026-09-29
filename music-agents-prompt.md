# Project: Multi-agent music generation system

## Goal
Build a multi-agent system where each agent handles one instrument and one agent composes. Output is a MIDI file. 

## Working style
- Do NOT build everything at once. Work one phase at a time and stop for my review after each phase.
- Do not install anything system-wide. Use a Python venv in the project folder only. (Python 3.11+ is available.)
- Do not put the project inside OneDrive.
- Never ask me to paste my API key into chat, and never write it into any file. It is read only from the `ANTHROPIC_API_KEY` environment variable, which I set myself.
- Keep code simple and readable. Add tests for anything that doesn't call the model.

## Core design
LLMs cannot produce audio, so agents write **symbolic music** (JSON note events). Plain Python turns it into MIDI.

- Note event: `{pitch, start_beat, duration, velocity}` per instrument.
- Drum hits quantized to a 16th-note grid.
- Rendering: `pretty_midi` (or `mido`) writes the `.mid` file. Audio rendering (FluidSynth, portable binary kept inside the project folder, no OS install) is optional and comes last.

## Agents (Version 1: pipeline, build this first)
Each agent is one Claude API call with its own system prompt, output schema and pitch range. Python code controls the order. Use forced tool calls with a JSON schema so output is well-formed.

| # | Agent | Sees | Produces |
|---|-------|------|----------|
| 1 | **Composer** | User prompt (e.g. "sad lo-fi, 80 BPM") | Blueprint, not notes: key, tempo, time signature, sections with bar counts, a chord per bar, instruments per section. The single shared contract. |
| 2 | **Drums** | Blueprint | Groove. Goes first among instruments. |
| 3 | **Bass** | Blueprint + drums | Bass line locked to the kick. |
| 4 | **Chords** (piano/guitar) | Blueprint + drums + bass | Voiced chords following the progression. |
| 5 | **Melody** | Everything so far | The tune. Goes last. |
| 6 | **Critic** (bounded, added last) | Assembled song as data | Verdict plus at most 3 issues, each naming the responsible agent and bars. Only flagged agents revise the flagged bars. |

Each instrument agent sees only the blueprint and the parts written before it, not other agents' prompts or reasoning.

## Validator (plain code, not an agent)
Runs after every agent:

- Valid JSON / schema
- Notes in range
- Notes in key
- Correct bar lengths
- No bad overlaps

On failure, send the exact error back to the same agent and retry (max 2-3 retries). Objective errors are caught by code; subjective/structural issues by the critic.

## Critic loop limits
- Max 2 critic rounds.
- Max 3 issues per round.
- Only revise flagged agents and bars.
- Keep the best version so far (if a revision is worse, keep the previous).
- Global cap on total API calls per run.
- Fixed rubric: groove, harmonic fit, variation between sections, balance/density.

## Models
Default `claude-sonnet-5-5` for all agents. Model per agent must be a setting. Optionally try `claude-opus-5-5` for the composer only if blueprints are weak.

## Flow

```
prompt -> Composer -> blueprint
blueprint                        -> Drums   -> validate -> (retry or accept)
blueprint + drums                -> Bass    -> validate -> (retry or accept)
blueprint + drums + bass         -> Chords  -> validate -> (retry or accept)
blueprint + all previous parts   -> Melody  -> validate -> (retry or accept)
assemble -> Critic (max 2 rounds) -> flagged agents revise -> validate -> re-assemble
keep best version -> write .mid
```

## Phases (stop after each for review)
0. **Setup:** venv, dependencies (`pretty_midi`, `anthropic`, `pytest`), project skeleton.
1. **Music pipeline with NO AI:** hand-written JSON becomes a `.mid` file I can play.
2. **Schemas and validator** with tests (blueprint, note event, in-key/in-range checks).
3. **Composer + one melody agent**, 8 bars. Output must pass the validator. (First phase needing the API key.)
4. **Add drums and bass**, passing earlier parts as context.
5. **Add chords**, the validator retry loop, and full song structure.
6. **Add the bounded critic loop.**
7. **Version 2: more autonomy, one step at a time:**
   - a. Each agent gets a self-check tool (`check_my_part`) and becomes a tool-using loop.
   - b. Composer becomes an orchestrator deciding which instruments to call and in what order.
   - c. Agents can push feedback to the composer, which may revise the blueprint.
   - Version 1 components (schemas, validator, MIDI writer, blueprint format) must carry over unchanged.
8. **Optional:** audio rendering, and porting to Flower AgentApps. It is unverified whether Flower supports agent-to-agent calls, so phases 0-7 must not depend on Flower.

## Testing
- Keep 3-4 fixed prompts (e.g. "sad lo-fi, 80 BPM", "upbeat funk") and rerun after each change so versions can be compared by ear.
- Unit tests for the validator and MIDI writer that make no model calls.
- Test the critic on deliberately bad songs to check it catches real problems.

## Known risks
- Rhythm/timing is hardest for LLMs: quantize to a grid, give drums pattern templates, let code fix small timing errors.
- Enforce key and chord tones in the validator, not just in prompts.
- Cost/latency: cap retries, run one instrument at a time while developing.

## First task
Start with **Phase 0 only**. Propose the folder structure and dependency list, then wait for my approval before creating anything.
