# Voice Module

Text-to-speech synthesis with automatic caching and SSML support.

## Quick Start

```python
from freebuff.voice import speak

# Basic synthesis
wav_path = speak("Ohm's Law states that V equals I times R", lang="en")

# With SSML pauses for teaching cadence
wav_path = speak("Ohm's Law. V equals I times R.", lang="en", use_ssml=True)
```

## How It Works

### speak(text, lang, use_ssml)

1. If `use_ssml=True`, wraps text in SSML with natural pauses
2. Checks cache — same text+lang never synthesised twice
3. Dispatches to the configured TTS engine (Piper or Cloud TTS)
4. Returns path to cached WAV file

**Caching:** SHA-256 hash of `text:lang` determines the cache key. Different text or different language = different cache file. This prevents burning through Cloud TTS allowance on repeated test runs.

### to_ssml(text)

Converts plain text to SSML for natural teaching cadence:

- **500ms pause** after sentences (`.`, `!`, `?`)
- **300ms pause** after commas for breathing
- Wrapped in `<speak>` tags for Piper compatibility

```python
from freebuff.voice.speak import to_ssml

result = to_ssml("Hello world. How are you? I am fine, thank you.")
# Output: <speak>Hello world. <break time="500ms"/> How are you?
#         <break time="500ms"/> I am fine, <break time="300ms"/>
#         thank you.</speak>
```

SSML and non-SSML calls produce different cache entries, so the same
plain text with and without SSML generates separate WAV files.

### split_audio(path, max_seconds, output_dir)

Splits a WAV file into chunks of `max_seconds` each using stdlib `wave`.
Returns a list of output paths in order.

```python
from freebuff.voice.speak import split_audio

# Split a 3-minute lesson into 60-second chunks
parts = split_audio("lesson.wav", max_seconds=60)
# Returns: ["cache/voice/abc_part000.wav",
#           "cache/voice/abc_part001.wav",
#           "cache/voice/abc_part002.wav"]
```

**When to use:** The avatar renderer refuses audio over 60 seconds.
Before calling `render_avatar()`, split long audio:

```python
from freebuff.voice.speak import split_audio
from freebuff.avatar import render_avatar

for chunk in split_audio("long_lesson.wav", max_seconds=60):
    render_avatar(chunk, "teacher.jpg")
```

### audio_duration(path)

Returns the duration of a WAV file in seconds. Uses stdlib `wave` —
no external dependencies.

```python
from freebuff.voice.speak import audio_duration

dur = audio_duration("segment.wav")  # e.g., 3.7
```

## TTS Backends

### Piper (Development)

Local, free, unlimited. Runs on CPU with no API key.

```yaml
# config.yaml
voice:
  engine: piper
  piper_voices:
    en: en_US-lessac-medium
    hi: hi_IN-swara-medium
```

Voice models are ONNX files in `voices/`. Download from
[huggingface.co/rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices).

### Google Cloud TTS (Final Demo)

Better quality, requires billing account. Only used when `engine: cloud_tts`.

```yaml
voice:
  engine: cloud_tts
```

Set `GOOGLE_APPLICATION_CREDENTIALS` env var to your service account JSON.

### Adding a New Backend

1. Create `freebuff/voice/my_backend.py`:
```python
def synthesize_my_backend(text, lang, output_path):
    # Your synthesis logic here
    pass
```

2. Add to the engine dispatch in `speak.py`:
```python
elif engine == "my_backend":
    from freebuff.voice.my_backend import synthesize_my_backend
    synthesize_my_backend(ssml_text, lang, output)
```

3. Set in config:
```yaml
voice:
  engine: my_backend
```

## Configuration

All voice settings in `config.yaml` under `voice:`:

| Key | Default | Description |
|-----|---------|-------------|
| `engine` | `piper` | TTS backend (`piper` or `cloud_tts`) |
| `output_dir` | `cache/voice` | Cache directory for WAV files |
| `piper_voices` | `{}` | Language → voice model mapping |

Override via environment variables:
```bash
export FREEBUFF_VOICE_ENGINE=cloud_tts
```
