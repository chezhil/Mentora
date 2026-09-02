"""Graph/plot renderer using matplotlib.

Renders function plots and data graphs filling the full canvas.
Designed for phone viewing: large axis labels, thick lines.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from . import register, save_figure, IMAGE_WIDTH, IMAGE_HEIGHT, DPI, BG_COLOR, TITLE_COLOR, ACCENT_COLORS


@register("graph")
def render_graph(content: str, subject: str, data: dict) -> str:
    """Render a plot/graph filling the full 1280x720 canvas.
    
    Data options:
    - data["function"]: string like "np.sin(x)" to plot
    - data["x_values"], data["y_values"]: lists of data points
    - data["x_min"], data["x_max"]: range for function plots
    - data["title"]: custom title
    - data["x_label"], data["y_label"]: axis labels
    """
    fig, ax = plt.subplots(1, 1, figsize=(IMAGE_WIDTH/DPI, IMAGE_HEIGHT/DPI), dpi=DPI)
    ax.set_facecolor(BG_COLOR)
    fig.patch.set_facecolor(BG_COLOR)

    # Large fonts for phone viewing
    title_size = 28
    label_size = 22
    tick_size = 16

    plotted = False

    # Plot data points if provided
    if "x_values" in data and "y_values" in data:
        x = np.array(data["x_values"])
        y = np.array(data["y_values"])
        ax.plot(x, y, "o-", color=ACCENT_COLORS[0], linewidth=3, markersize=10,
                markerfacecolor="white", markeredgecolor=ACCENT_COLORS[0], markeredgewidth=2)
        plotted = True

    # Plot function if provided
    elif "function" in data:
        func_str = data["function"]
        x = np.linspace(data.get("x_min", -10), data.get("x_max", 10), 500)
        try:
            safe_ns = {
                "x": x, "np": np,
                "sin": np.sin, "cos": np.cos, "tan": np.tan,
                "exp": np.exp, "log": np.log, "sqrt": np.sqrt,
                "pi": np.pi, "abs": np.abs,
            }
            y = eval(func_str, {"__builtins__": {}}, safe_ns)
            ax.plot(x, y, color=ACCENT_COLORS[0], linewidth=3)
            plotted = True
        except Exception as e:
            ax.text(0.5, 0.5, f"Cannot plot: {func_str}\n{e}",
                    transform=ax.transAxes, ha="center", va="center",
                    fontsize=24, color="#e74c3c")

    # Default: show content as a demo sine wave
    if not plotted:
        x = np.linspace(0, 2 * np.pi, 200)
        y = np.sin(x)
        ax.plot(x, y, color=ACCENT_COLORS[0], linewidth=3)
        ax.set_title(f"Graph: {content[:40]}", fontsize=title_size, color=TITLE_COLOR, pad=20)

    # Style: large grid, thick spines
    ax.grid(True, alpha=0.3, linewidth=1.5)
    for spine in ax.spines.values():
        spine.set_linewidth(2)
        spine.set_color("#cccccc")
    ax.tick_params(axis="both", which="major", labelsize=tick_size, width=2, length=6)

    # Large axis labels
    ax.set_xlabel(data.get("x_label", "X"), fontsize=label_size, fontweight="bold", labelpad=10)
    ax.set_ylabel(data.get("y_label", "Y"), fontsize=label_size, fontweight="bold", labelpad=10)

    # Title
    title = data.get("title", content[:50])
    ax.set_title(title, fontsize=title_size, fontweight="bold", color=TITLE_COLOR, pad=20)

    # Add padding so content doesn't touch edges
    plt.subplots_adjust(left=0.08, right=0.95, top=0.90, bottom=0.10)

    return save_figure(fig, "graph")
