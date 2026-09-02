
from pathlib import Path
import re

NL = chr(10)
BS = chr(92)  # backslash
DQ = chr(34)  # double quote

# Build the regex replacement strings
# We need: r" <break time=\"500ms\"/> "
# Which in the file should be: r" <break time="500ms"/> "

repl1 = BS + '1 <break time=' + DQ + '500ms' + DQ + '/> '
repl2 = ', <break time=' + DQ + '300ms' + DQ + '/> '

# Build the function
fn = []
fn.append('def to_ssml(text):')
fn.append('    import re')
fn.append('    text = re.sub(r"([.!?]) +", r"' + repl1 + '", text)')
fn.append('    text = re.sub(r", +", "' + repl2 + '", text)')
fn.append('    return "<speak>" + text + "</speak>"')

# Test it
code = NL.join(fn)
print('Testing function:')
print(code)
print()
exec(code)
result = to_ssml('Hello world. How are you? I am fine, thank you.')
print('Result:', result)
print('Has speak tags:', result.startswith('<speak>') and result.endswith('</speak>'))
print('Has sentence pause:', '500ms' in result)
print('Has comma pause:', '300ms' in result)
print()

# Now build the full file
lines = []
lines.append('# Synthesise text to speech with automatic caching.')
lines.append('')
lines.append('from __future__ import annotations')
lines.append('import logging')
lines.append('import re')
lines.append('import wave')
lines.append('import shutil')
lines.append('from freebuff.cache import cache_path, get_cached, cache_key, _cache_dir')
lines.append('from pathlib import Path')
lines.append('from freebuff.config import get_config')
lines.append('')
lines.append('logger = logging.getLogger(__name__)')
lines.append('')
lines.append('')
lines.extend(fn)
lines.append('')
lines.append('')
lines.append('def speak(text, lang="en", use_ssml=False):')
lines.append('    if not text or not text.strip():')
lines.append('        raise ValueError("Cannot synthesise empty text")')
lines.append('')
lines.append('    # Apply SSML wrapping before caching')
lines.append('    ssml_text = to_ssml(text) if use_ssml else text')
lines.append('')
lines.append('    cached = get_cached("voice", ".wav", ssml_text, lang)')
lines.append('    if cached:')
lines.append('        return cached')
lines.append('')
lines.append('    cfg = get_config().get("voice", {})')
lines.append('    engine = cfg.get("engine", "piper")')
lines.append('    output = cache_path("voice", ".wav", ssml_text, lang)')
lines.append('')
lines.append('    if engine == "piper":')
lines.append('        from freebuff.voice.piper_backend import synthesize_piper')
lines.append('        synthesize_piper(ssml_text, lang, output)')
lines.append('    else:')
lines.append('        raise ValueError(f"Unknown engine: {engine}")')
lines.append('    return str(output)')

# Read existing file to get split_audio and audio_duration
old = Path('freebuff/voice/speak.py').read_text()
idx = old.find('def split_audio')
rest = old[idx:] if idx > 0 else ''

# Write the file
Path('freebuff/voice/speak.py').write_text(NL.join(lines) + NL + NL + rest)
print('Wrote speak.py')
