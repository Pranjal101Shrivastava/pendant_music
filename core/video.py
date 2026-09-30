"""Convert a .mid to .mp4 using only pip-installable libraries.

MIDI -> WAV: pure numpy synthesizer (sine waves + harmonics + ADSR envelope).
WAV  -> MP4: imageio-ffmpeg (bundles ffmpeg — no system install needed).

    render_mp4("outputs/my-song/song.mid", "outputs/my-song/song.mp4")
"""

import os
import subprocess
import wave
import numpy as np
from pretty_midi import PrettyMIDI

SAMPLE_RATE = 44100


def _synthesize(midi_path: str, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    midi = PrettyMIDI(midi_path)
    duration = midi.get_end_time()
    n_samples = int(np.ceil(duration * sample_rate)) + sample_rate  # +1 s tail
    audio = np.zeros(n_samples, dtype=np.float32)

    for instrument in midi.instruments:
        for note in instrument.notes:
            start = int(note.start * sample_rate)
            end = int(note.end * sample_rate)
            length = end - start
            if length <= 0:
                continue

            velocity = note.velocity / 127.0
            t = np.arange(length, dtype=np.float32) / sample_rate

            if instrument.is_drum:
                chunk = np.random.default_rng(note.pitch).standard_normal(length).astype(np.float32)
                rel = min(int(0.08 * sample_rate), length)
                chunk[-rel:] *= np.linspace(1.0, 0.0, rel, dtype=np.float32)
            else:
                freq = 440.0 * (2.0 ** ((note.pitch - 69) / 12.0))
                chunk = (
                    np.sin(2 * np.pi * freq * t)
                    + 0.4 * np.sin(2 * np.pi * 2 * freq * t)
                    + 0.2 * np.sin(2 * np.pi * 3 * freq * t)
                ).astype(np.float32)
                atk = min(int(0.01 * sample_rate), length // 4)
                dec = min(int(0.05 * sample_rate), length // 4)
                rel = min(int(0.10 * sample_rate), length // 3)
                env = np.ones(length, dtype=np.float32)
                if atk:
                    env[:atk] = np.linspace(0.0, 1.0, atk)
                if dec and atk + dec < length:
                    env[atk: atk + dec] = np.linspace(1.0, 0.7, dec)
                env[-rel:] *= np.linspace(1.0, 0.0, rel)
                chunk *= env

            chunk *= velocity * 0.08
            end_idx = min(start + length, n_samples)
            audio[start:end_idx] += chunk[: end_idx - start]

    peak = np.max(np.abs(audio))
    if peak > 0:
        audio *= 0.9 / peak
    return audio


def _write_wav(audio: np.ndarray, wav_path: str, sample_rate: int = SAMPLE_RATE) -> None:
    pcm = (audio * 32767).astype(np.int16)
    with wave.open(wav_path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def render_mp4(midi_path: str, mp4_path: str, sample_rate: int = SAMPLE_RATE,
               keep_wav: bool = False) -> str:
    import imageio_ffmpeg  # imported here so offline/audio-only runs don't need the package

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    wav_path = mp4_path.replace(".mp4", "_tmp.wav")

    audio = _synthesize(midi_path, sample_rate)
    _write_wav(audio, wav_path, sample_rate)

    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", wav_path, "-c:a", "aac", "-b:a", "192k", mp4_path],
            check=True, capture_output=True,
        )
    finally:
        if not keep_wav and os.path.exists(wav_path):
            os.remove(wav_path)

    return mp4_path
