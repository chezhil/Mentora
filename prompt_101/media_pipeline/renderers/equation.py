"""Equation/formula renderer using matplotlib.

Renders equations with large, readable text filling the full canvas.
Designed for phone viewing: large fonts, high contrast.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import register, save_figure, IMAGE_WIDTH, IMAGE_HEIGHT, DPI, BG_COLOR, TITLE_COLOR, TEXT_COLOR, ACCENT_COLORS


@register("equation")
def render_equation(content: str, subject: str, data: dict) -> str:
    """Render equation/formula filling the full 1280x720 canvas.
    
    Content can be:
    - Single equation: "E = mc^2"
    - Multi-line with \\n: "E = mc^2\\nwhere E is energy\\nand m is mass"
    - With data["steps"]: list of derivation steps
    """
    fig, ax = plt.subplots(1, 1, figsize=(IMAGE_WIDTH/DPI, IMAGE_HEIGHT/DPI), dpi=DPI)
    ax.set_facecolor(BG_COLOR)
    fig.patch.set_facecolor(BG_COLOR)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # Parse content
    lines = content.split("\n") if "\n" in content else [content]
    steps = data.get("steps", [])
    all_lines = lines + steps

    n_lines = len(all_lines)

    # Title at top
    ax.text(0.5, 0.92, "Equation", fontsize=32, fontweight="bold",
            ha="center", va="center", color=ACCENT_COLORS[0])

    # Divider line
    ax.plot([0.1, 0.9], [0.87, 0.87], color=ACCENT_COLORS[0],
            linewidth=2, alpha=0.3, transform=ax.transAxes, clip_on=False)

    # Main equation (large, centered in upper portion)
    main_eq = all_lines[0] if all_lines else content

    # Calculate font size based on equation length
    eq_len = len(main_eq)
    if eq_len < 15:
        main_fontsize = 72
    elif eq_len < 25:
        main_fontsize = 56
    elif eq_len < 40:
        main_fontsize = 44
    else:
        main_fontsize = 36

    # Main equation in a styled box
    ax.text(0.5, 0.65, main_eq, fontsize=main_fontsize, fontweight="bold",
            ha="center", va="center", color=TITLE_COLOR, fontfamily="serif",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                      edgecolor=ACCENT_COLORS[0], linewidth=3, alpha=0.95))

    # Additional lines (steps, derivations, explanations)
    if n_lines > 1:
        remaining = all_lines[1:]
        step_fontsize = max(20, min(28, 400 // max(len(remaining), 1)))

        y_start = 0.38
        y_step = min(0.12, 0.30 / max(len(remaining), 1))

        for i, line in enumerate(remaining):
            y = y_start - i * y_step
            if y < 0.05:
                break

            # Number the steps
            prefix = f"{i+1}. " if steps else ""
            color = ACCENT_COLORS[(i + 1) % len(ACCENT_COLORS)]

            ax.text(0.5, y, f"{prefix}{line}", fontsize=step_fontsize,
                    ha="center", va="center", color=TEXT_COLOR,
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                              edgecolor=color, linewidth=1.5, alpha=0.8))

    # Subject tag at bottom
    if subject:
        ax.text(0.5, 0.04, subject.title(), fontsize=18,
                ha="center", va="center", color="#888888", fontstyle="italic")

    return save_figure(fig, "equation")
