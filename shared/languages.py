"""Every language Mentora offers, defined once.

WHY THIS FILE EXISTS

The language list used to live in app.py, the voice mapping in
prompt_101/media_pipeline/voice.py, and the font stack in
prompt_101/media_pipeline/renderers/__init__.py. Adding a language meant
editing three files, and forgetting one of them produced the two worst
failures we had: a language that speaks but draws its diagram labels as empty
boxes, and a language that renders but narrates in silence.

So a language is defined here, once, with everything needed to actually
deliver a lesson in it:

    voice   the edge-tts neural voice (male and female)
    piper   the offline Piper model, where one exists
    font    the matplotlib family that can draw the script, or None for Latin
    rtl     right-to-left, so the visuals can lay text out correctly

Nothing is listed here that has not been checked end to end. A language that
half works is worse than one we do not offer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    english_name: str
    native_name: str
    voice_female: str
    voice_male: str
    font: str | None = None       # None means DejaVu Sans covers the script
    piper: str | None = None      # offline voice, where one exists
    rtl: bool = False

    @property
    def label(self) -> str:
        """What the picker shows: native name first, English after."""
        if self.native_name == self.english_name:
            return self.english_name
        return f"{self.native_name} · {self.english_name}"


# Ordered as the picker shows them: English, then Indian languages, then the
# rest. Hinglish sits with the Indian set because that is where it belongs to
# the people who use it.
LANGUAGES: dict[str, Language] = {
    lang.code: lang for lang in [
        Language("en", "English", "English",
                 "en-IN-NeerjaNeural", "en-IN-PrabhatNeural",
                 piper="en_US-lessac-medium"),
        Language("hi", "Hindi", "हिन्दी",
                 "hi-IN-SwaraNeural", "hi-IN-MadhurNeural",
                 font="Noto Sans Devanagari", piper="hi_IN-pratham-medium"),
        Language("hinglish", "Hinglish", "Hinglish",
                 "hi-IN-SwaraNeural", "hi-IN-MadhurNeural",
                 font="Noto Sans Devanagari"),
        Language("bn", "Bengali", "বাংলা",
                 "bn-IN-TanishaaNeural", "bn-IN-BashkarNeural",
                 font="Noto Sans Bengali"),
        Language("mr", "Marathi", "मराठी",
                 "mr-IN-AarohiNeural", "mr-IN-ManoharNeural",
                 font="Noto Sans Devanagari"),
        Language("ta", "Tamil", "தமிழ்",
                 "ta-IN-PallaviNeural", "ta-IN-ValluvarNeural",
                 font="Noto Sans Tamil"),
        Language("te", "Telugu", "తెలుగు",
                 "te-IN-ShrutiNeural", "te-IN-MohanNeural",
                 font="Noto Sans Telugu", piper="te_IN-maya-medium"),
        Language("kn", "Kannada", "ಕನ್ನಡ",
                 "kn-IN-SapnaNeural", "kn-IN-GaganNeural",
                 font="Noto Sans Kannada"),
        Language("ml", "Malayalam", "മലയാളം",
                 "ml-IN-SobhanaNeural", "ml-IN-MidhunNeural",
                 font="Noto Sans Malayalam"),
        Language("gu", "Gujarati", "ગુજરાતી",
                 "gu-IN-DhwaniNeural", "gu-IN-NiranjanNeural",
                 font="Noto Sans Gujarati"),
        Language("ur", "Urdu", "اردو",
                 "ur-IN-GulNeural", "ur-IN-SalmanNeural",
                 font="Noto Sans Arabic", rtl=True),
        Language("ar", "Arabic", "العربية",
                 "ar-EG-SalmaNeural", "ar-EG-ShakirNeural",
                 font="Noto Sans Arabic", rtl=True),
        Language("es", "Spanish", "Español",
                 "es-ES-ElviraNeural", "es-ES-AlvaroNeural"),
        Language("fr", "French", "Français",
                 "fr-FR-DeniseNeural", "fr-FR-HenriNeural"),
        Language("de", "German", "Deutsch",
                 "de-DE-KatjaNeural", "de-DE-ConradNeural"),
        Language("pt", "Portuguese", "Português",
                 "pt-BR-FranciscaNeural", "pt-BR-AntonioNeural"),
        Language("ru", "Russian", "Русский",
                 "ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"),
        Language("id", "Indonesian", "Bahasa Indonesia",
                 "id-ID-GadisNeural", "id-ID-ArdiNeural"),
    ]
}

DEFAULT = "en"

# Indian languages get billing in the picker — the brief awards extra credit
# for them, and it is who the app is for.
INDIAN = ("hi", "hinglish", "bn", "mr", "ta", "te", "kn", "ml", "gu", "ur")


def get(code: str) -> Language:
    """The language, falling back to English rather than raising."""
    return LANGUAGES.get(code) or LANGUAGES[DEFAULT]


def codes() -> list[str]:
    return list(LANGUAGES)


def label(code: str) -> str:
    return get(code).label


def voice(code: str, gender: str = "female") -> str:
    lang = get(code)
    return lang.voice_male if gender == "male" else lang.voice_female


def font_stack() -> list[str]:
    """Every font matplotlib needs, DejaVu first for Latin.

    matplotlib falls through this list per glyph, so one stack draws every
    script we offer. It must be the explicit family list — the "sans-serif"
    alias resolves to a single font and stops.
    """
    fonts = ["DejaVu Sans"]
    for lang in LANGUAGES.values():
        if lang.font and lang.font not in fonts:
            fonts.append(lang.font)
    return fonts
