# Offline commands

Vosk small English is the offline engine; no LLM or API key is used. Exact commands/synonyms are parsed deterministically. UI text commands share the same intent router. Ambiguous text produces a clarification response; no deletion intent exists.

- Radio check; Status; How much fuel? / Fuel status; Can I finish?; How much do I need to save?; When should I pit?
- Box this lap; Last lap; Best lap; Delta to reference (honest unavailable response until live alignment is implemented).
- Where am I losing time?; What happened that lap?; Compare with my best (evidence cards, not fabricated precise comparisons).
- How are the tyres? / How are the tires? (surface readings; not wear/pressure).
- Use the last lap as reference (in-memory selection only); Mark this corner; Mark that incident.
- Show live; Show analysis; Show strategy.
- Repeat; Speak less; Speak more; Quiet for two minutes; Mute; Stop talking; Resume engineer; End session.
- Text input supports `Set target lap time 1:32.500` or `set target lap time one minute thirty two seconds`, and `save a note TEXT`.

The constrained microphone grammar currently includes fixed command aliases and [unk]. Variable target times/free-form notes are accepted through text but are **not reliably supported in the microphone grammar**. Number parsing does not imply free-dictation support. Short follow-up dialogue context and wake phrases are not implemented.

Setup: see INSTALL_ORANGE_PI. Initialize mic, hold PTT, speak and release. A selected local keyboard Space key on the focused Live Race PTT button is supported. Recognition requires average word confidence >=0.7 by default. PTT has a short post-cancel guard and a 12-second capture cap. The engineer does not speak while the worker reports listening. Headset echo cancellation and hands-free barge-in are not claimed.

Audio calibration/test uses two seconds in memory, reports RMS/peak/clipping, and can play it back to the selected output. It is not retained. Calibration reports a suggested threshold; no VAD feature silently consumes it. A bad device/model/rate shows an error; manual Initialize retries the worker. Automatic device reconnect/resampling are incomplete.
