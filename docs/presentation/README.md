# Pendant presentation

Open `presentation.html` in a browser. All audio is embedded and works offline.
Keep `index.html` and `our-song.html` beside it for the full-size demo links.
Arrow keys or Back/Next navigate; N toggles speaker notes.

- Slide 1 plays an eight-second intentionally off-key example.
- Slide 4 embeds the Glitch Stutter recorded-stem demo (source 00:40–01:00).
- Slide 5 embeds Bright Pop Short from `outputs/bright-pop-100-bpm/song.json`
  (100 BPM, C major, source 00:09.6–00:29.6).
- Slide 6 closes the presentation.

Both demos include animated players, synchronized waveforms, mute/solo, seeking,
pause/resume, and before/after melody comparison. Leaving a demo slide unloads
its player to stop playback.

## Audio provenance and scope

Glitch Stutter uses user-supplied downloaded stems grouped into drums/percussion,
bass, keys/guitar, and synth/remaining parts. Its altered melody is raised one
semitone with duration preserved. The original backing is shared across takes.

Bright Pop Short uses the repository's saved note pitches, timing, durations,
and velocities, rendered with a deterministic local synthesizer. These are not
original audio recordings or a General MIDI soundfont render. The comparison
raises the melody one semitone while keeping all backing parts unchanged.
The source report lists five OpenAI calls and no critic rounds. The animated
workflow and critic dialogue are illustrative, not evidence of live generation
or an actual recorded revision run.

## Validation

Verified in Chromium: all five audio buffers per demo decode to 20 seconds;
four parts play together; melody solo silences the other parts; before/after
switching preserves position; leaving a slide unloads its player. The complete
recorded-stem sequence was also run through to completion.
