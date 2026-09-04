# Voice

`prompt_101/media_pipeline/voice.py` — one function, `speak(text, lang)`,
returning a path to a WAV.

```python
from prompt_101.media_pipeline import speak

wav = speak("Ohm's Law states that V equals I times R", lang="en")
wav = speak("धारा चालक में आवेश का प्रवाह है।", lang="hi")
```

> This file previously documented a `freebuff.voice` module, an `use_ssml`
> argument and a Google Cloud TTS backend. None of those exist. The Cloud TTS
> path needed a paid account the team does not have, and selecting Tamil used
> to raise `ImportError` in the middle of a lesson; it was removed rather than
> left as a path that could only fail.

## Two backends, both free, no key anywhere

| Backend | Covers | Why it is there |
|---|---|---|
| **edge-tts** | all 18 languages | Microsoft's neural voices. Clearly better than the alternative, and the only backend with voices for Tamil, Kannada, Malayalam, Gujarati and the rest. Needs a network connection. |
| **Piper** | en, hi, te | Local and offline. The fallback for when the network is not there — which is the case a live demo has to survive. |

Edge leads. That is the opposite of how it used to be: Piper led because it
works offline, and the result was that the three most-used languages had the
worst narration in the app while five better voices sat unused. Offline is
worth having as a fallback, not as a default.

If both fail, `speak()` returns a silent placeholder of roughly the right
length and prints why. It never raises — a voice failure degrades a lesson;
it must not end one.

## Voices

Every voice is declared in `shared/languages.py`, next to that language's font
and script direction, so a language cannot be added that speaks but cannot
draw its own alphabet. Both a female and a male voice are named for each.

## Delivery

`SPEECH_RATE` defaults to `-8%`. A teacher explaining something new speaks a
little below conversational pace, and the default rate reads as rushed against
a diagram the student is still taking in.

## Caching

Keyed on `sha256(text + lang + voice gender)`. The same sentence in the same
language and voice is never synthesised twice. The gender is part of the key
because without it, switching voice replayed the previous one out of cache and
looked like the setting did nothing.

## Environment

| Variable | Effect |
|---|---|
| `MENTORA_VOICE=male` | Use the male voice for every language |
| `MENTORA_SPEECH_RATE` | Override the delivery rate, e.g. `-15%` |
| `MENTORA_SPEECH_PITCH` | Override pitch, e.g. `+2Hz` |
| `TTS_PROVIDER=piper` | Force the offline backend |

## Output format

22050 Hz, mono, 16-bit WAV — which is what Wav2Lip's mel extraction and the
ffmpeg compositor both expect. edge-tts returns MP3, so it is transcoded on
the way out.

## Verified

All 18 languages were checked end to end: real audio (RMS above the silence
floor), correct duration, and a font that can draw the same text on the
visuals. See the language table in the README.
