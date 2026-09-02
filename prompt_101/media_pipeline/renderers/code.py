"""Code renderer using matplotlib.

Renders syntax-highlighted code filling the full canvas.
Uses matplotlib only (no Pygments dependency for rendering).
"""
import re
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

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


@register("code")
def render_code(content: str, subject: str, data: dict) -> str:
    """Render syntax-highlighted code filling the full 1280x720 canvas.
    
    Data options:
    - data["language"]: programming language (default: "python")
    - data["title"]: filename/title for the title bar
    """
    language = data.get("language", "python")
    title = data.get("title", "Code")

    fig, ax = plt.subplots(1, 1, figsize=(IMAGE_WIDTH/DPI, IMAGE_HEIGHT/DPI), dpi=DPI)
    ax.set_facecolor("#1e1e2f")
    fig.patch.set_facecolor("#1e1e2f")
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # ── Title bar ──
    ax.add_patch(FancyBboxPatch((0.02, 0.93), 0.96, 0.055,
                                boxstyle="round,pad=0.008",
                                facecolor="#2d2d44", edgecolor="#444466",
                                linewidth=1.5, transform=ax.transAxes))
    # Window dots
    for i, c in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]):
        circle = plt.Circle((0.045 + i * 0.018, 0.9575), 0.006,
                            facecolor=c, edgecolor="none",
                            transform=ax.transAxes, zorder=5)
        ax.add_patch(circle)

    ax.text(0.10, 0.9575, title, fontsize=14, color="#cccccc",
            transform=ax.transAxes, va="center", fontfamily="monospace")

    # Language tag
    ax.text(0.95, 0.9575, language, fontsize=11, color="#888888",
            transform=ax.transAxes, va="center", ha="right", fontfamily="monospace")

    # ── Code content ──
    code_lines = content.split("\n")
    n_lines = len(code_lines)

    # Calculate layout
    y_start = 0.90
    y_end = 0.04
    available_height = y_start - y_end

    # Dynamic font size: fit all lines or use max readable size
    if n_lines <= 15:
        font_size = 18
        line_height = available_height / max(n_lines, 1)
    elif n_lines <= 25:
        font_size = 14
        line_height = available_height / max(n_lines, 1)
    else:
        font_size = 12
        line_height = min(0.035, available_height / max(n_lines, 1))

    # Character width in axes units (monospace is ~0.6 * font_size in points)
    # For 1280px wide figure at 100 DPI, 1 axes unit = 1280 pixels
    # A monospace char at 18pt is roughly 10.8 pixels wide
    char_width = font_size * 0.00055  # Approximate in axes coordinates

    # Left margin for line numbers
    line_num_width = 0.04  # Space for line numbers

    for i, line in enumerate(code_lines):
        y = y_start - i * line_height
        if y < y_end:
            # Show truncation indicator
            ax.text(0.95, y_end + 0.01, f"... {n_lines - i} more lines",
                    fontsize=11, color="#888888",
                    transform=ax.transAxes, ha="right", fontfamily="monospace")
            break

        # Line number (right-aligned in its column)
        line_num = f"{i+1:3d}"
        ax.text(line_num_width, y, line_num, fontsize=font_size - 2,
                color="#858585", transform=ax.transAxes, va="top",
                fontfamily="monospace", ha="right")

        # Tokenize and render the line
        tokens = _tokenize_line(line, language)
        x_pos = line_num_width + 0.01  # Start after line numbers

        for token_text, token_type in tokens:
            color = _get_color(token_type)
            ax.text(x_pos, y, token_text, fontsize=font_size, color=color,
                    transform=ax.transAxes, va="top", fontfamily="monospace")
            x_pos += len(token_text) * char_width

    # ── Bottom status bar ──
    ax.add_patch(FancyBboxPatch((0.02, 0.005), 0.96, 0.025,
                                boxstyle="round,pad=0.003",
                                facecolor="#2d2d44", edgecolor="none",
                                transform=ax.transAxes))
    ax.text(0.04, 0.0175, f"Lines: {n_lines}", fontsize=10, color="#888888",
            transform=ax.transAxes, va="center", fontfamily="monospace")

    return save_figure(fig, "code")
