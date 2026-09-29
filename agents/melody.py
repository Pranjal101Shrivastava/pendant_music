"""Melody agent: the tune. Goes last and sees everything written before it."""

from agents.base import InstrumentAgent

GUIDANCE = """\
You write the lead melody - the part people hum. ONE note at a time (each note ends
before the next begins).

- Build it from a short motif (2-5 notes) and develop it: repeat, vary the ending,
  sequence it to fit the next chord. Question-and-answer phrases of 2 or 4 bars.
- Chord tones on strong beats, stepwise motion and scale notes in between. End phrases on
  a chord tone held a little longer, and let the melody breathe with rests.
- Stay mostly between D4 and A5 (62-81), above the chords. Choruses can sit higher and
  be denser than verses; intros/outros sparser.
- Rhythm on 16ths or triplets. Leave room around the drum fills.
"""

AGENT = InstrumentAgent("melody", GUIDANCE)
