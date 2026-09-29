"""Critic agent: reviews the assembled song as data and names at most 3 issues, each
with the responsible agent and bars. It never edits anything itself."""

import json
from typing import Callable, Dict, List

from core.analysis import analyze
from core.config import Settings
from core.describe import describe_blueprint, describe_parts
from core.json_schemas import CRITIC_REPORT
from core.llm import LLMOutputError
from core.timeline import total_bars

Log = Callable[[str], None]
RUBRIC = ["groove", "harmonic_fit", "variation", "balance"]

SYSTEM = """\
You are the band's critic and producer. You receive a finished arrangement as data: the
blueprint, every part (bar by bar), and objective measurements from code. Judge it with
this fixed rubric, each scored 1-5:
- groove: drums keep a clear, genre-appropriate pulse; bass locks to the kick.
- harmonic_fit: parts follow the chords; strong beats land on chord tones.
- variation: sections differ in energy and density; the melody develops rather than loops.
- balance: every instrument has its own register and space; nothing is too dense or missing.

Return verdict "accept" if the song works, otherwise "revise" with AT MOST 3 issues, most
important first. Each issue names ONE agent (drums, bass, chords or melody), the bar range
it applies to (as small as possible) and a concrete fix that agent can act on. Only flag
real problems - the flagged agents will rewrite exactly those bars.
"""


def review(llm, settings: Settings, bp: dict, parts: Dict[str, List[dict]], round_: int,
           log: Log = print) -> dict:
    measured = analyze(bp, parts)
    request = "\n\n".join([
        describe_blueprint(bp),
        describe_parts(parts, bp),
        "Measurements from code:\n" + json.dumps({"scores": measured["scores"],
                                                   "details": measured["details"]}, indent=1),
        f"This is critic round {round_}. Review the song.",
    ])
    messages = [{"role": "user", "content": request}]
    context = {"blueprint": bp, "parts": parts, "max_issues": settings.max_issues}
    try:
        report = llm.generate(agent="critic", system=SYSTEM, messages=messages,
                              schema_name="critic_report", schema=CRITIC_REPORT, context=context)
    except LLMOutputError as e:
        log(f"  critic: unusable answer ({e}); using the measured scores")
        report = {"verdict": "accept", "scores": measured["scores"], "summary": "critic unavailable",
                  "issues": []}
    return clean_report(report, bp, parts, settings.max_issues)


def clean_report(report: dict, bp: dict, parts: Dict[str, List[dict]], max_issues: int) -> dict:
    """Enforce the plan's limits no matter what the model returned."""
    n = total_bars(bp)
    scores = {k: max(1.0, min(5.0, float(report.get("scores", {}).get(k, 3)))) for k in RUBRIC}
    issues = []
    for issue in report.get("issues", []):
        if issue.get("agent") not in parts:
            continue
        first = max(1, min(n, int(issue.get("first_bar", 1))))
        last = max(first, min(n, int(issue.get("last_bar", first))))
        issues.append({"agent": issue["agent"], "first_bar": first, "last_bar": last,
                       "problem": str(issue.get("problem", "")), "fix": str(issue.get("fix", ""))})
        if len(issues) == max_issues:
            break
    verdict = report.get("verdict", "accept")
    if not issues:
        verdict = "accept"
    return {"verdict": verdict, "scores": scores, "score": round(sum(scores.values()) / len(scores), 2),
            "summary": str(report.get("summary", "")), "issues": issues if verdict == "revise" else []}
