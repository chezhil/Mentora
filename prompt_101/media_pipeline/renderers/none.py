"""Title card / placeholder renderer.

Never crashes, always returns a valid path.
Used when no specific visual type is appropriate.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import register, save_figure, IMAGE_WIDTH, IMAGE_HEIGHT, DPI, BG_COLOR, TITLE_COLOR, TEXT_COLOR, ACCENT_COLORS


@register("none")
def render_none(content: str, subject: str, data: dict) -> str:
    """Render a title card filling the full 1280x720 canvas.
    
    This is the safety net - always succeeds.
    """
    fig, ax = plt.subplots(1, 1, figsize=(IMAGE_WIDTH/DPI, IMAGE_HEIGHT/DPI), dpi=DPI)
    ax.set_facecolor(BG_COLOR)
    fig.patch.set_facecolor(BG_COLOR)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # Gradient background using colored rectangles
    cmap = plt.cm.coolwarm
    for i in range(40):
        rgba = cmap(i / 40)
        ax.add_patch(plt.Rectangle((0, i / 40), 1, 1 / 40,
                                    transform=ax.transAxes,
                                    facecolor=rgba, alpha=0.25,
                                    edgecolor="none"))

    # Central decorative element
    center_circle = plt.Circle((0.5, 0.55), 0.18, color=ACCENT_COLORS[0],
                               alpha=0.15, transform=ax.transAxes)
    ax.add_patch(center_circle)

    # Title - very large
    display_title = data.get("title", "Title Card")
    ax.text(0.5, 0.62, display_title, fontsize=44, fontweight="bold",
            ha="center", va="center", color=TITLE_COLOR,
            transform=ax.transAxes)

    # Content text
    display_text = content[:80] if content else "Visual content"
    ax.text(0.5, 0.42, display_text, fontsize=24,
            ha="center", va="center", color=TEXT_COLOR,
            transform=ax.transAxes)

    # Bottom decoration
    ax.plot([0.3, 0.7], [0.30, 0.30], color=ACCENT_COLORS[0],
            linewidth=3, alpha=0.5, transform=ax.transAxes)

    # Subject tag
    if subject:
        ax.text(0.5, 0.22, subject.title(), fontsize=20,
                ha="center", va="center", color="#888888", fontstyle="italic",
                transform=ax.transAxes)

    return save_figure(fig, "placeholder")
