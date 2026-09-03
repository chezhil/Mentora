# Multilingual Implementation

## Overview

The media pipeline supports 7 languages across 5 Indian scripts plus English, with multilingual rendering in both visuals and voice.

## Supported Languages

| Language | Code | Script | Piper Voice | Google Voice | Font |
|----------|------|--------|-------------|--------------|------|
| English | `en` | Latin | `en_US-lessac-medium` | `en-US-Wavenet-D` | Noto Sans |
| Hindi | `hi` | Devanagari | `hi_IN-rohan-medium` | `hi-IN-Wavenet-A` | Noto Sans Devanagari |
| Tamil | `ta` | Tamil | *(Google only)* | `ta-IN-Wavenet-A` | Noto Sans Tamil |
| Telugu | `te` | Telugu | `te_IN-maya-medium` | `te-IN-Wavenet-A` | Noto Sans Telugu |
| Bengali | `bn` | Bengali | `bn_BD-google-medium` | `bn-IN-Wavenet-A` | Noto Sans Bengali |
| Kannada | `kn` | Kannada | *(Google only)* | `kn-IN-Wavenet-A` | Noto Sans Kannada |
| Marathi | `mr` | Devanagari | `mr_IN-google-medium` | `mr-IN-Wavenet-A` | Noto Sans Devanagari |

## Script Coverage

All 5 major Indian scripts are supported:

1. **Devanagari** (हिन्दी, मराठी) — Hindi and Marathi
2. **Tamil** (தமிழ்) — Tamil
3. **Telugu** (తెలుగు) — Telugu
4. **Bengali** (বাংলা) — Bengali
5. **Kannada** (ಕನ್ನಡ) — Kannada

## Indic Font System

### Font Registration

Noto Sans fonts for all 5 scripts are stored in `assets/fonts/` and registered with matplotlib at import time:

```
assets/fonts/
├── NotoSans-Regular.ttf            # Latin fallback
├── NotoSansDevanagari-Regular.ttf  # Hindi, Marathi
├── NotoSansTamil-Regular.ttf       # Tamil
├── NotoSansTelugu-Regular.ttf      # Telugu
├── NotoSansBengali-Regular.ttf     # Bengali
└── NotoSansKannada-Regular.ttf     # Kannada
```

### Font Fallback Mechanism

Matplotlib doesn't support font stacks in `fontfamily`. Instead, we prepend the Indic font to `rcParams['font.sans-serif']`:

```python
# In renderers/__init__.py
matplotlib.rcParams['font.sans-serif'] = [indic_font] + current_list
```

This ensures:
- Indic characters render with Noto Sans for the script
- Latin characters (numbers, operators, ASCII) fall back to DejaVu Sans
- Mixed-script content (e.g., "E = mc²" in Hindi) renders correctly

### Language-to-Script Mapping

```python
_LANG_TO_SCRIPT = {
    "en": "latin",
    "hi": "devanagari",
    "mr": "devanagari",
    "ta": "tamil",
    "te": "telugu",
    "bn": "bengali",
    "kn": "kannada",
}
```

## How Language Flows Through the Pipeline

### Visual Rendering

Each renderer accepts language via `data["lang"]`:

```python
render("equation", "a₂ = a₁ + d", subject="maths", data={"lang": "hi"})
```

The renderer calls `get_font_family(lang)` to get the appropriate font, then uses it for all text elements.

### Voice Synthesis

```python
speak("नमस्ते, यह हिंदी परीक्षा है।", lang="hi")
```

The `speak()` function resolves the provider (piper or google) based on the language and generates audio.

### Visual Kinds × Languages

All 7 visual kinds render in all 6 languages:

| Kind | English | Hindi | Tamil | Telugu | Bengali | Kannada |
|------|---------|-------|-------|--------|---------|---------|
| equation | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| graph | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| diagram | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| timeline | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| code | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| concept_map | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| none | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

## Adding a New Language

### Step 1: Font

1. Download Noto Sans font for the script from [Google Noto Fonts](https://github.com/googlefonts/noto-fonts)
2. Place in `assets/fonts/NotoSans{Script}-Regular.ttf`
3. Add mapping in `renderers/__init__.py`:
   ```python
   _INDIC_FONTS["script_name"] = "NotoSansScript-Regular.ttf"
   _LANG_TO_SCRIPT["xx"] = "script_name"
   ```

### Step 2: Voice

1. Check [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) for Piper model
2. If exists: add to `PIPER_VOICES` in `voice.py`, download model
3. If not: add to `GOOGLE_ONLY_LANGUAGES` and `GOOGLE_VOICES`

### Step 3: Test

Run the visual verification test:
```python
render("equation", "Your test text", subject="physics", data={"lang": "xx"})
```

And voice verification:
```python
speak("Your test text", lang="xx")
```

## Limitations

1. **Bold font weight**: Indic Noto Sans fonts only have weight 400 (regular). Matplotlib falls back to regular when bold is requested — text renders but isn't bold.

2. **Mixed-script content**: Equations with Latin symbols (E = mc², a₂ = a₁ + d) rely on font fallback. The Latin glyphs come from DejaVu Sans, which may have slightly different metrics than the Indic font.

3. **Tamil and Kannada voice**: No Piper models exist upstream. These languages require Google Cloud TTS credentials (`GOOGLE_APPLICATION_CREDENTIALS`) to produce audio. Without credentials, a silent placeholder is generated.

4. **Code renderer**: Always uses monospace font regardless of language. Indic text in code blocks may render with fallback glyphs.
