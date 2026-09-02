"""Visual Rendering, Voice, Avatar, Video Assembly - Pair C (Santosh + Hamza)

Public API:
    render()          - Generate PNG visuals for all 7 kinds
    choose_visual()   - Determine appropriate visual type for a concept
    speak()           - Generate WAV audio with caching
    render_avatar()   - Create talking head MP4 via LivePortrait
    compose()         - Assemble visual + avatar + audio into segment MP4
    stitch()          - Concatenate segments into final video
"""

from .visual import render, choose_visual
from .voice import speak
from .avatar import render_avatar
from .compositor import compose, stitch

__all__ = [
    "render",
    "choose_visual",
    "speak",
    "render_avatar",
    "compose",
    "stitch",
]

# Version
__version__ = "0.1.0"
