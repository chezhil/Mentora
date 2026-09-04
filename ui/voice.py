"""Voice mode — browser-native Web Speech API for TTS playback.

Uses st.html() with unsafe_allow_javascript=True to inject JS directly
into the page DOM (not in an isolated iframe), so __speak() persists
and can be called from subsequent st.html() calls.
"""

import streamlit as st


_JS_INJECTED_KEY = "_voice_js_injected"


def _inject_voice_js() -> None:
    """Inject the Web Speech API JavaScript once per page load."""
    if st.session_state.get(_JS_INJECTED_KEY):
        return
    st.session_state[_JS_INJECTED_KEY] = True

    js = """
    <script>
    if (!window.__voiceReady) {
      window.__voiceReady = true;

      window.__speak = function(text, rate) {
        if (!('speechSynthesis' in window)) return;
        window.speechSynthesis.cancel();
        var utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = rate || 1.0;
        utterance.pitch = 1.0;
        window.speechSynthesis.speak(utterance);
      };

      window.__stopSpeaking = function() {
        if ('speechSynthesis' in window) window.speechSynthesis.cancel();
      };
    }
    </script>
    """
    st.html(js, unsafe_allow_javascript=True)


def speak_text(text: str, rate: float = 1.0) -> None:
    """Read text aloud using browser TTS."""
    _inject_voice_js()
    safe = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
    # Escape for safe embedding in a JS string literal
    safe = safe.replace('"', '\\"').replace("`", "\\`")
    st.html(
        f"<script>if(window.__speak)window.__speak('{safe}', {rate})</script>",
        unsafe_allow_javascript=True,
    )


def stop_speaking() -> None:
    """Stop any in-progress TTS."""
    _inject_voice_js()
    st.html(
        "<script>if(window.__stopSpeaking)window.__stopSpeaking()</script>",
        unsafe_allow_javascript=True,
    )
