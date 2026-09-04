"""Code renderer using matplotlib.

Renders syntax-highlighted code filling the full canvas.
Uses matplotlib only (no Pygments dependency for rendering).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from . import register, save_figure, IMAGE_WIDTH, IMAGE_HEIGHT, DPI


# ── Syntax colors (VS Code dark theme inspired) ──
COLOR_DEFAULT = "#d4d4d4"    # Light gray - normal text
COLOR_KEYWORD = "#569cd6"    # Blue - keywords
COLOR_STRING = "#ce9178"     # Orange - strings
COLOR_COMMENT = "#6a9955"    # Green - comments
COLOR_NUMBER = "#b5cea8"     # Light green - numbers
COLOR_FUNCTION = "#dcdcaa"   # Yellow - function names
COLOR_DECORATOR = "#dcdcaa"  # Yellow - decorators
COLOR_OPERATOR = "#d4d4d4"   # Light gray - operators

# ── Language keyword sets ──
KEYWORDS = {
    "python": {
        "False", "None", "True", "and", "as", "assert", "async", "await",
        "break", "class", "continue", "def", "del", "elif", "else", "except",
        "finally", "for", "from", "global", "if", "import", "in", "is",
        "lambda", "nonlocal", "not", "or", "pass", "raise", "return",
        "try", "while", "with", "yield",
    },
    "javascript": {
        "async", "await", "break", "case", "catch", "class", "const",
        "continue", "debugger", "default", "delete", "do", "else",
        "export", "extends", "finally", "for", "from", "function",
        "if", "import", "in", "instanceof", "let", "new", "of",
        "return", "static", "super", "switch", "this", "throw",
        "try", "typeof", "var", "void", "while", "with", "yield",
        "true", "false", "null", "undefined",
    },
    "java": {
        "abstract", "assert", "boolean", "break", "byte", "case", "catch",
        "char", "class", "const", "continue", "default", "do", "double",
        "else", "enum", "extends", "final", "finally", "float", "for",
        "goto", "if", "implements", "import", "instanceof", "int",
        "interface", "long", "native", "new", "package", "private",
        "protected", "public", "return", "short", "static", "strictfp",
        "super", "switch", "synchronized", "this", "throw", "throws",
        "transient", "try", "void", "volatile", "while",
        "true", "false", "null",
    },
    "c": {
        "auto", "break", "case", "char", "const", "continue", "default",
        "do", "double", "else", "enum", "extern", "float", "for", "goto",
        "if", "inline", "int", "long", "register", "restrict", "return",
        "short", "signed", "sizeof", "static", "struct", "switch",
        "typedef", "union", "unsigned", "void", "volatile", "while",
        "_Bool", "_Complex", "_Imaginary",
    },
    "cpp": {
        "alignas", "alignof", "and", "asm", "auto", "bool", "break",
        "case", "catch", "char", "class", "const", "constexpr", "continue",
        "decltype", "default", "delete", "do", "double", "dynamic_cast",
        "else", "enum", "explicit", "export", "extern", "false", "float",
        "for", "friend", "goto", "if", "inline", "int", "long", "mutable",
        "namespace", "new", "noexcept", "nullptr", "operator", "private",
        "protected", "public", "register", "return", "short", "signed",
        "sizeof", "static", "static_cast", "struct", "switch", "template",
        "this", "throw", "true", "try", "typedef", "typeid", "typename",
        "union", "unsigned", "using", "virtual", "void", "volatile", "while",
    },
}


def _tokenize_line(line: str, language: str) -> list:
    """Tokenize a line of code into (text, token_type) pairs.
    
    Token types: 'keyword', 'string', 'comment', 'number', 'function', 'text'
    """
    tokens = []
    i = 0
    n = len(line)
    kw_set = KEYWORDS.get(language, KEYWORDS["python"])

    while i < n:
        ch = line[i]

        # Comment (# or //)
        if ch == "#" or (ch == "/" and i + 1 < n and line[i + 1] == "/"):
            tokens.append((line[i:], "comment"))
            break

        # Block comment start (/*)
        if ch == "/" and i + 1 < n and line[i + 1] == "*":
            end = line.find("*/", i + 2)
            if end == -1:
                tokens.append((line[i:], "comment"))
                break
            tokens.append((line[i:end + 2], "comment"))
            i = end + 2
            continue

        # Triple-quoted strings (''' or """)
        if line[i:i+3] in ('"""', "'''"):
            quote = line[i:i+3]
            end = line.find(quote, i + 3)
            if end == -1:
                tokens.append((line[i:], "string"))
                break
            tokens.append((line[i:end + 3], "string"))
            i = end + 3
            continue

        # Single/double quoted strings
        if ch in ('"', "'"):
            # Check for f-string or r-string prefix
            prefix_start = i
            if i > 0 and line[i-1] in ('f', 'r', 'b'):
                prefix_start = i - 1

            quote = ch
            j = i + 1
            while j < n and line[j] != quote:
                if line[j] == "\\":
                    j += 1
                j += 1
            j = min(j + 1, n)
            tokens.append((line[prefix_start:j], "string"))
            i = j
            continue

        # Words (identifiers, keywords)
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (line[j].isalnum() or line[j] == "_"):
                j += 1
            word = line[i:j]

            # Check if it's a keyword
            if word in kw_set:
                tokens.append((word, "keyword"))
            # Check if followed by ( -> function call
            elif j < n and line[j] == "(":
                tokens.append((word, "function"))
            # Check if preceded by @ -> decorator
            elif i > 0 and line[i-1] == "@":
                tokens.append((word, "decorator"))
            else:
                tokens.append((word, "text"))
            i = j
            continue

        # Numbers
        if ch.isdigit() or (ch == "." and i + 1 < n and line[i+1].isdigit()):
            j = i
            while j < n and (line[j].isdigit() or line[j] in ".xXeE"):
                j += 1
            tokens.append((line[i:j], "number"))
            i = j
            continue

        # Decorator (@)
        if ch == "@":
            tokens.append((ch, "decorator"))
            i += 1
            continue

        # Operators and punctuation
        tokens.append((ch, "text"))
        i += 1

    return tokens if tokens else [(" ", "text")]


def _get_color(token_type: str) -> str:
    """Map token type to color."""
    return {
        "keyword": COLOR_KEYWORD,
        "string": COLOR_STRING,
        "comment": COLOR_COMMENT,
        "number": COLOR_NUMBER,
        "function": COLOR_FUNCTION,
        "decorator": COLOR_DECORATOR,
        "text": COLOR_DEFAULT,
    }.get(token_type, COLOR_DEFAULT)


# ── Layout ──────────────────────────────────────────────────────────────────
#
# Two bugs lived in the old layout and both are visible in any screenshot of
# it. First, the width of a monospace character was guessed at
# `font_size * 0.00055` axes units, which is about 16% narrower than DejaVu
# Sans Mono actually is — so every token was drawn slightly left of where the
# one before it ended, and `def resistance(v, i):` came out as overlapping
# glyphs reading `def resistanc(e, i):`. Second, the line height was the whole
# canvas divided by the number of lines, so a four-line snippet was spread out
# with 150px between lines.
#
# Both are now measured rather than guessed: the character advance comes from
# the renderer, and the line height follows the font size.

EDITOR_BG = "#12100E"        # matches design.INK, so it sits in the family
CHROME_BG = "#262320"
GUTTER = "#7A736C"


def _char_width(fig, ax, font_size: float) -> float:
    """Width of one monospace character, in axes units. Measured, not guessed."""
    probe = ax.text(0, 0, "M" * 50, fontsize=font_size, fontfamily="monospace",
                    transform=ax.transAxes, alpha=0)
    fig.canvas.draw()
    box = probe.get_window_extent(fig.canvas.get_renderer())
    probe.remove()
    return box.width / 50.0 / fig.bbox.width


@register("code")
def render_code(content: str, subject: str, data: dict) -> str:
    """Render syntax-highlighted code filling the full 1280x720 canvas.

    Data options:
    - data["language"]: programming language (default: "python")
    - data["title"]: filename/title for the title bar
    """
    language = str(data.get("language", "python"))
    title = str(data.get("title") or "Code")

    fig, ax = plt.subplots(1, 1, figsize=(IMAGE_WIDTH / DPI, IMAGE_HEIGHT / DPI),
                           dpi=DPI)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    ax.set_facecolor(EDITOR_BG)
    fig.patch.set_facecolor(EDITOR_BG)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # ── Title bar ──
    ax.add_patch(Rectangle((0, 0.925), 1, 0.075, facecolor=CHROME_BG,
                           edgecolor="none", transform=ax.transAxes, zorder=2))
    ax.plot([0, 1], [0.925, 0.925], color="#4A4540", linewidth=2,
            transform=ax.transAxes, zorder=3, clip_on=False)
    for i, colour in enumerate(["#FF5A36", "#FFD400", "#00B37E"]):
        ax.add_patch(plt.Circle((0.022 + i * 0.020, 0.9625), 0.007,
                                facecolor=colour, edgecolor="none",
                                transform=ax.transAxes, zorder=4))
    ax.text(0.095, 0.9625, title, fontsize=17, color="#E8E3DC", va="center",
            transform=ax.transAxes, fontfamily="monospace", zorder=4)
    ax.text(0.985, 0.9625, language, fontsize=13, color=GUTTER, va="center",
            ha="right", transform=ax.transAxes, fontfamily="monospace", zorder=4)

    # ── Code ──
    lines = str(content).replace("\t", "    ").split("\n")
    # Drop leading and trailing blank lines; they only eat vertical room.
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        lines = ["(no code in this payload)"]

    top, floor = 0.885, 0.055
    room = top - floor
    widest = max(len(line) for line in lines)

    # Pick the largest size at which every line fits both ways, then let the
    # line height follow from it rather than stretching to fill the canvas.
    for font_size in (20, 18, 16, 14, 12, 10):
        line_height = font_size * 1.62 / (IMAGE_HEIGHT / DPI * 72)
        gutter_chars = 4
        char_w = font_size * 0.6 * 1.39 / IMAGE_WIDTH
        if (len(lines) * line_height <= room
                and (widest + gutter_chars) * char_w <= 0.94):
            break

    char_w = _char_width(fig, ax, font_size)
    x_gutter = 0.030
    x_code = 0.052
    y = top

    for i, line in enumerate(lines):
        if y - line_height < floor:
            ax.text(0.98, floor - 0.005, f"... {len(lines) - i} more lines",
                    fontsize=max(11, font_size - 4), color=GUTTER,
                    transform=ax.transAxes, ha="right", va="top",
                    fontfamily="monospace", zorder=4)
            break

        ax.text(x_gutter, y, f"{i + 1:2d}", fontsize=font_size - 2,
                color=GUTTER, transform=ax.transAxes, va="top", ha="right",
                fontfamily="monospace", zorder=4)

        x = x_code
        for text, kind in _tokenize_line(line, language):
            if text.strip():
                ax.text(x, y, text, fontsize=font_size, color=_get_color(kind),
                        transform=ax.transAxes, va="top",
                        fontfamily="monospace", zorder=4)
            x += len(text) * char_w
        y -= line_height

    return save_figure(fig, "code")
