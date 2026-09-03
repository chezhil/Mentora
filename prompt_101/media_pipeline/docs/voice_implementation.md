# Voice Implementation

## Overview

The voice synthesis system generates speech audio from text using a unified `speak()` function that supports two TTS providers behind a single interface.

---

## Architecture

```
speak(text, lang)
    │
    ├── Check cache (hash-based)
    │
    └── _resolve_provider(lang)
         │
         ├── Provider "auto" (default):
         │    ├── lang in PIPER_VOICES → Piper (local, free)
         │    └── lang NOT in PIPER_VOICES → Google Cloud TTS
         │
         ├── Provider "piper" → Force Piper for all languages
         └── Provider "google" → Force Google for all languages
```

## Provider Selection (Auto Mode)

The `TTS_PROVIDER` config defaults to `"auto"`, which selects the best provider per language:

| Language | Code | Provider | Voice Model | Source |
|----------|------|----------|-------------|--------|
| English | `en` | Piper | `en_US-lessac-medium` | Local |
| Hindi | `hi` | Piper | `hi_IN-rohan-medium` | Local |
| Telugu | `te` | Piper | `te_IN-maya-medium` | Local |
| Bengali | `bn` | Piper | `bn_BD-google-medium` | Local |
| Marathi | `mr` | Piper | `mr_IN-google-medium` | Local |
| Tamil | `ta` | **Google Cloud TTS** | `ta-IN-Wavenet-A` | Cloud |
| Kannada | `kn` | **Google Cloud TTS** | `kn-IN-Wavenet-A` | Cloud |

### Why Tamil and Kannada Use Google Cloud TTS

Piper's upstream voice repository ([rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)) does not include Tamil (`ta`) or Kannada (`kn`) voices. The `GOOGLE_ONLY_LANGUAGES` set in `voice.py` lists these languages so the auto-router sends them to Google Cloud TTS automatically.

## Piper Implementation

### Model Loading

The `piper-tts` Python package provides `PiperVoice.load()` which loads ONNX model files directly — no CLI binary required.

```python
from piper import PiperVoice

voice = PiperVoice.load("path/to/te_IN-maya-medium.onnx")
audio_chunks = list(voice.synthesize(text))
```

### Model Directory

Models are stored in `prompt_101/media_pipeline/piper_models/` as flat files:

```
piper_models/
├── en_US-lessac-medium.onnx
├── en_US-lessac-medium.onnx.json
├── hi_IN-rohan-medium.onnx
├── hi_IN-rohan-medium.onnx.json
├── te_IN-maya-medium.onnx
├── te_IN-maya-medium.onnx.json
└── ...
```

### Fallback Chain

1. **Python API** (preferred): `PiperVoice.load()` + `synthesize()`
2. **CLI subprocess** (fallback): `piper --model X --output_file Y`
3. **Placeholder** (last resort): Silent WAV file proportional to text length

## Google Cloud TTS Implementation

### Credentials

Set via environment variable:
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

Or in `.env`:
```
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

### API Usage

```python
from google.cloud import texttospeech

client = texttospeech.TextToSpeechClient()
voice = texttospeech.VoiceSelectionParams(
    language_code="ta-IN",
    name="ta-IN-Wavenet-A",
)
response = client.synthesize_speech(input=..., voice=voice, audio_config=...)
```

### Monthly Free Allowance

Google Cloud TTS provides 1 million characters/month free (WaveNet voices) and 4 million characters/month free (Standard voices).

## Caching

All TTS output is cached using SHA256 hash of `(text, lang)`:

```
output/tts/tts_{hash}.wav
```

Same text + language = same hash = same file, never regenerated.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `TTS_PROVIDER` | `"auto"` | `"auto"`, `"piper"`, or `"google"` |
| `PIPER_MODEL_DIR` | `media_pipeline/piper_models/` | Directory for Piper ONNX models |
| `GOOGLE_APPLICATION_CREDENTIALS` | `None` | Path to Google Cloud service account |

## Adding a New Language

1. Check [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) for a Piper model
2. If Piper model exists:
   - Add to `PIPER_VOICES` dict in `voice.py`
   - Download the `.onnx` and `.onnx.json` files to `piper_models/`
3. If no Piper model:
   - Add language code to `GOOGLE_ONLY_LANGUAGES` set
   - Add voice name to `GOOGLE_VOICES` dict
   - Ensure `GOOGLE_APPLICATION_CREDENTIALS` is set
4. Add language code to `_LANG_TO_SCRIPT` in `renderers/__init__.py` for font support
