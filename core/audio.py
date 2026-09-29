"""Phase 8 (optional): render a .mid to .wav with FluidSynth.

No system-wide install needed: put a portable FluidSynth build in tools/fluidsynth/
and a General MIDI SoundFont (.sf2) in soundfonts/ (both are git-ignored), or point
the FLUIDSYNTH and PENDANT_SOUNDFONT environment variables at them. A fluidsynth
already on PATH also works.
"""

import glob
import os
import shutil
import subprocess
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEM_SOUNDFONTS = ["/usr/share/sounds/sf2/FluidR3_GM.sf2", "/usr/share/soundfonts/FluidR3_GM.sf2",
                     "/usr/share/sounds/sf2/default-GM.sf2"]


def find_fluidsynth() -> Optional[str]:
    candidates = [os.environ.get("FLUIDSYNTH", "")]
    for name in ("fluidsynth", "fluidsynth.exe"):
        candidates += glob.glob(os.path.join(ROOT, "tools", "fluidsynth", "**", name), recursive=True)
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return shutil.which("fluidsynth")


def find_soundfont() -> Optional[str]:
    candidates = [os.environ.get("PENDANT_SOUNDFONT", "")]
    candidates += sorted(glob.glob(os.path.join(ROOT, "soundfonts", "*.sf2")))
    candidates += SYSTEM_SOUNDFONTS
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def render_wav(midi_path: str, wav_path: str, sample_rate: int = 44100) -> str:
    fluidsynth, soundfont = find_fluidsynth(), find_soundfont()
    if not fluidsynth:
        raise FileNotFoundError("FluidSynth not found - put a portable build in tools/fluidsynth/ "
                                "or set FLUIDSYNTH=/path/to/fluidsynth")
    if not soundfont:
        raise FileNotFoundError("No SoundFont found - put a General MIDI .sf2 in soundfonts/ "
                                "or set PENDANT_SOUNDFONT=/path/to/file.sf2")
    subprocess.run([fluidsynth, "-ni", "-g", "0.7", "-F", wav_path, "-r", str(sample_rate),
                    soundfont, midi_path], check=True, capture_output=True)
    return wav_path
