"""Chords agent (piano, guitar, pads...): voiced chords following the progression."""

from agents.base import InstrumentAgent

GUIDANCE = """\
You play the harmony (piano, keys, guitar or pad - the composer picked the sound).

- Voice each bar's chord with 3-5 notes, mostly between C3 and C5 (48-72), never more
  than 6 notes sounding at once.
- Voice-lead: keep common tones and move other voices by step between chords instead of
  jumping to root position every bar.
- Stay under the melody's register, and leave the bass its low end (don't double the
  bass line below C3).
- Rhythm by genre: pop steady 8th or quarter pulses; lo-fi and ballads held chords;
  funk short off-beat 16th stabs; jazz Charleston comping (beat 1 and the "+" of 2);
  rock driving 8ths; ambient long pads. Follow the drums' accents.
- The same pitch can't start again while it is still ringing - end a note before
  repeating it.
"""

AGENT = InstrumentAgent("chords", GUIDANCE)
