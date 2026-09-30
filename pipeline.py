"""Main entry point - runs the full agent pipeline.

    python pipeline.py "sad lo-fi, 80 BPM"                 # 16 bars, offline if no API key
    python pipeline.py "upbeat funk, 110 BPM" --bars 8
    python pipeline.py --all                               # every prompt in prompts.json
    python pipeline.py "dreamy ambient" --mode autonomous  # version 2 (phase 7)
    python pipeline.py "energetic jazz" --provider openai --audio

Flow (version 1):
    prompt -> composer -> blueprint
    drums -> bass -> chords -> melody   (each validated; errors go back for 2 retries)
    critic (max 2 rounds, max 3 issues) -> flagged agents rewrite flagged bars
    keep the best-scoring version -> .mid (+ .wav with --audio)
Version 2 (--mode autonomous) adds: agents self-check with a tool (7a), the composer
chooses who plays and in what order (7b), agents send feedback and the composer may
revise the blueprint (7c).
"""

import argparse
import copy
import json
import os
import re
import sys
from typing import Callable, Dict, List

from dotenv import load_dotenv
load_dotenv()  # loads .env from the project root before any env reads

from agents import bass, chords, composer, critic, drums, melody
from agents.base import AgentFailed
from core.config import Settings
from core.llm import BudgetExceeded, CallBudget, LLMError, make_provider
from core.schemas import make_song
from core.midi_writer import write_midi
from core.timeline import roles_in_order, total_bars

INSTRUMENTS = {"drums": drums.AGENT, "bass": bass.AGENT, "chords": chords.AGENT, "melody": melody.AGENT}
ROOT = os.path.dirname(os.path.abspath(__file__))

Log = Callable[[str], None]


def _show(path: str) -> str:
    rel = os.path.relpath(path, ROOT)
    return path if rel.startswith("..") else rel


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "song"


def write_parts(llm, settings: Settings, bp: dict, order: List[str], log: Log) -> tuple:
    parts: Dict[str, List[dict]] = {}
    feedback: Dict[str, str] = {}
    stats: Dict[str, dict] = {}
    for role in order:
        result = INSTRUMENTS[role].write(llm, settings, bp, dict(parts), log)
        parts[role] = result.notes
        feedback[role] = result.feedback
        stats[role] = {"attempts": result.attempts, "repairs": result.repaired}
    return parts, feedback, stats


def critic_loop(llm, settings: Settings, bp: dict, parts: Dict[str, List[dict]], log: Log) -> tuple:
    """Bounded review: at most `critic_rounds` rounds of revisions, at most `max_issues`
    per round, only flagged agents rewrite only flagged bars, and the best-scoring version
    wins even if a revision made things worse."""
    history = []
    current = parts
    revised_since_review = False
    try:
        for round_ in range(1, settings.critic_rounds + 1):
            report = critic.review(llm, settings, bp, current, round_, log)
            history.append({"round": round_, "parts": current, "report": report})
            revised_since_review = False
            log(f"  critic round {round_}: {report['verdict']} (score {report['score']}) {report['summary']}")
            if report["verdict"] == "accept":
                break
            current = copy.deepcopy(current)
            for issue in report["issues"]:
                log(f"    -> {issue['agent']} bars {issue['first_bar']}-{issue['last_bar']}: {issue['problem']}")
                try:
                    result = INSTRUMENTS[issue["agent"]].revise(llm, settings, bp, current, issue, round_, log)
                    current[issue["agent"]] = result.notes
                    revised_since_review = True
                except AgentFailed as e:
                    log(f"    revision failed, keeping the old bars: {e}")
        if revised_since_review:  # score the last revision too, so keep-best can compare
            report = critic.review(llm, settings, bp, current, settings.critic_rounds + 1, log)
            history.append({"round": settings.critic_rounds + 1, "parts": current, "report": report})
            log(f"  critic final check: score {report['score']}")
    except BudgetExceeded as e:
        log(f"  critic stopped early: {e}")
    if not history:
        return parts, []
    best = max(history, key=lambda h: (h["report"]["score"], h["round"]))
    if best is not history[-1]:
        log(f"  keeping the version from round {best['round']} (score {best['report']['score']})")
    return best["parts"], [{"round": h["round"], **h["report"]} for h in history]


def run(prompt: str, settings: Settings, bars: int = 16, out_root: str = None, llm=None,
        audio: bool = False, mp4: bool = False, log: Log = print) -> dict:
    settings.validate()
    if type(bars) is not int or bars < 1:
        raise ValueError("bars must be a positive integer")
    budget = CallBudget(settings.max_api_calls)
    llm = llm or make_provider(settings, budget)
    if getattr(llm, "budget", None) is not None:
        budget = llm.budget
    log(f"\n=== {prompt!r} ({llm.name}, {bars} bars) ===")

    bp = composer.compose(llm, settings, prompt, bars, log)
    log(f"  blueprint: {bp.get('title', '')} - {bp['key']} {bp['mode']}, {bp['tempo']} BPM, "
        + ", ".join(f"{s['name']} {s['bars']}" for s in bp["sections"]))

    order = roles_in_order(bp)
    if settings.orchestrate:
        order, bp = composer.choose_order(llm, settings, bp, log)

    parts, feedback, stats = write_parts(llm, settings, bp, order, log)
    revisions = 0
    if settings.feedback:
        while revisions < settings.max_blueprint_revisions:
            revised = composer.consider_feedback(llm, settings, bp, feedback, log)
            if revised is None:
                break
            revisions += 1
            bp = revised
            order = [r for r in order if r in bp["instruments"]]
            order += [r for r in roles_in_order(bp) if r not in order]
            parts, feedback, stats = write_parts(llm, settings, bp, order, log)

    reports = []
    if settings.critic_rounds > 0:
        parts, reports = critic_loop(llm, settings, bp, parts, log)

    song = make_song(bp, parts)
    out_dir = os.path.join(out_root or os.path.join(ROOT, "outputs"), slugify(prompt))
    os.makedirs(out_dir, exist_ok=True)
    midi_path = os.path.join(out_dir, "song.mid")
    write_midi(song, midi_path)
    with open(os.path.join(out_dir, "song.json"), "w") as f:
        json.dump({"blueprint": bp, "song": song}, f, indent=1)
    report = {"prompt": prompt, "provider": llm.name, "bars": total_bars(bp), "order": order,
              "api_calls": budget.used, "calls_by_agent": budget.by_agent, "agents": stats,
              "feedback": feedback, "blueprint_revisions": revisions, "critic": reports}
    with open(os.path.join(out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    files = [midi_path]
    if audio:
        from core.audio import render_wav

        try:
            files.append(render_wav(midi_path, os.path.join(out_dir, "song.wav")))
        except (FileNotFoundError, OSError) as e:
            log(f"  audio skipped: {e}")
    if mp4:
        from core.video import render_mp4

        try:
            files.append(render_mp4(midi_path, os.path.join(out_dir, "song.mp4")))
        except (FileNotFoundError, OSError) as e:
            log(f"  mp4 skipped: {e}")
    log(f"  wrote {', '.join(_show(p) for p in files)} "
        f"({budget.used} calls: {budget.by_agent})")
    return {"blueprint": bp, "parts": parts, "song": song, "report": report, "out_dir": out_dir}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Multi-agent music generation -> MIDI")
    p.add_argument("prompt", nargs="?", help='e.g. "sad lo-fi, 80 BPM"')
    p.add_argument("--all", action="store_true", help="run every prompt in prompts.json")
    p.add_argument("--bars", type=int, default=16)
    p.add_argument("--provider", choices=["auto", "openai", "offline"], default=None,
                   help="auto = openai when OPENAI_API_KEY is set, else offline")
    p.add_argument("--mode", choices=["pipeline", "autonomous"], default="pipeline")
    p.add_argument("--critic-rounds", type=int, default=None)
    p.add_argument("--max-calls", type=int, default=None, help="global cap on model calls per run")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--audio", action="store_true", help="also render song.wav with FluidSynth")
    p.add_argument("--mp4", action="store_true", help="also render song.mp4 (FluidSynth + ffmpeg)")
    p.add_argument("--out", default=None, help="output folder (default outputs/)")
    args = p.parse_args(argv)
    if not args.prompt and not args.all:
        p.error("give a prompt or --all")

    autonomous = args.mode == "autonomous"
    settings = Settings.from_env(provider=args.provider, critic_rounds=args.critic_rounds,
                                 max_api_calls=args.max_calls, seed=args.seed,
                                 self_check=autonomous or None, orchestrate=autonomous or None,
                                 feedback=autonomous or None)
    prompts = [args.prompt] if args.prompt else json.load(open(os.path.join(ROOT, "prompts.json")))
    try:
        for prompt in prompts:
            run(prompt, settings, bars=args.bars, out_root=args.out, audio=args.audio, mp4=args.mp4)
    except (LLMError, AgentFailed, RuntimeError, ValueError) as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
