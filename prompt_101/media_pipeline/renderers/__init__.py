"""Renderer registry with lazy imports.

Each renderer is a function: (content, subject, data) -> path_to_png
Renderers are loaded on-demand so missing dependencies don't break the package.

Indic fonts (Noto Sans) are registered at import time for all 5 Indian scripts:
Devanagari (Hindi/Marathi), Tamil, Telugu, Bengali, Kannada.
"""
from pathlib import Path
import uuid

# ── Indic Font Registration ──
# Register Noto Sans fonts for all 5 Indian scripts so matplotlib can render
# Devanagari (Hindi, Marathi), Tamil, Telugu, Bengali, and Kannada text.
_FONTS_DIR = Path(__file__).parent.parent.parent / "assets" / "fonts"

# Script -> font file mapping
_INDIC_FONTS = {
    "devanagari": "NotoSansDevanagari-Regular.ttf",  # Hindi, Marathi
    "tamil": "NotoSansTamil-Regular.ttf",
    "telugu": "NotoSansTelugu-Regular.ttf",
    "bengali": "NotoSansBengali-Regular.ttf",
    "kannada": "NotoSansKannada-Regular.ttf",
    "latin": "NotoSans-Regular.ttf",  # English fallback
}

# Language code -> script mapping
_LANG_TO_SCRIPT = {
    "en": "latin",
    "hi": "devanagari",
    "mr": "devanagari",
    "ta": "tamil",
    "te": "telugu",
    "bn": "bengali",
    "kn": "kannada",
}

# Registered font families (populated at module load)
_INDIC_FONT_FAMILIES = {}

def _register_indic_fonts():
    """Register Noto Sans Indic fonts with matplotlib."""
    import matplotlib.font_manager as fm

    for script, font_file in _INDIC_FONTS.items():
        font_path = _FONTS_DIR / font_file
        if font_path.exists():
            try:
                fm.fontManager.addfont(str(font_path))
                prop = fm.FontProperties(fname=str(font_path))
                family = prop.get_name()
                _INDIC_FONT_FAMILIES[script] = family
            except Exception as e:
                print(f"[renderers] Warning: Could not register {font_file}: {e}")
        else:
            print(f"[renderers] Warning: Font not found: {font_path}")

_register_indic_fonts()

def get_font_family(lang: str = "en") -> str:
    """Get the appropriate font family for a language.
    
    For Indic scripts, sets the matplotlib rcParams so that the Indic font
    is tried first, with fallback to DejaVu Sans for Latin glyphs.
    This ensures mixed-script content (e.g., "E = mc²" in Hindi) renders
    correctly: Indic characters use Noto Sans, Latin characters fall back.
    
    Args:
        lang: Language code (en, hi, ta, te, bn, kn, mr)
    
    Returns:
        Matplotlib font family name (always "sans-serif").
    """
    import matplotlib
    script = _LANG_TO_SCRIPT.get(lang, "latin")
    indic_font = _INDIC_FONT_FAMILIES.get(script)
    if indic_font and script != "latin":
        # Prepend Indic font to sans-serif list so it's tried first.
        # Matplotlib falls back to subsequent fonts for missing glyphs.
        current = list(matplotlib.rcParams["font.sans-serif"])
        if indic_font not in current:
            matplotlib.rcParams["font.sans-serif"] = [indic_font] + current
    return "sans-serif"

# ── Shared Constants ──
IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 720
DPI = 100
BG_COLOR = "#f8f9fa"
TITLE_COLOR = "#1a1a2e"
TEXT_COLOR = "#333333"
ACCENT_COLORS = ["#667eea", "#764ba2", "#43b581", "#f5a623", "#e74c3c"]

# Output directory (set by visual.py on import)
OUTPUT_DIR = None

# Lazy-loaded renderer registry
_RENDERERS = {}
_LOADED = set()


def set_output_dir(path):
    """Set the output directory for rendered images."""
    global OUTPUT_DIR
    OUTPUT_DIR = Path(path)


def save_figure(fig, kind: str) -> str:
    """Save matplotlib figure to PNG at exactly 1280x720."""
    from PIL import Image as PILImage
    import matplotlib.pyplot as plt

    if OUTPUT_DIR is None:
        raise RuntimeError("OUTPUT_DIR not set. Call set_output_dir() first.")

    filename = f"visual_{kind}_{uuid.uuid4().hex[:8]}.png"
    output_path = OUTPUT_DIR / filename

    fig.savefig(output_path, dpi=DPI, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)

    # Enforce exact dimensions
    img = PILImage.open(output_path)
    if img.size != (IMAGE_WIDTH, IMAGE_HEIGHT):
        img = img.resize((IMAGE_WIDTH, IMAGE_HEIGHT), PILImage.LANCZOS)
        img.save(output_path)

    return str(output_path)


def _load_renderer(kind: str):
    """Lazy-load a renderer by kind. Raises ImportError if dependency missing."""
    if kind in _RENDERERS:
        return _RENDERERS[kind]
    
    if kind in _LOADED:
        # Already tried and failed
        raise ImportError(f"Renderer '{kind}' failed to load")
    
    _LOADED.add(kind)
    
    try:
        if kind == "equation":
            from .equation import render_equation
            _RENDERERS[kind] = render_equation
        elif kind == "graph":
            from .graph import render_graph
            _RENDERERS[kind] = render_graph
        elif kind == "diagram":
            from .diagram import render_diagram
            _RENDERERS[kind] = render_diagram
        elif kind == "timeline":
            from .timeline import render_timeline
            _RENDERERS[kind] = render_timeline
        elif kind == "code":
            from .code import render_code
            _RENDERERS[kind] = render_code
        elif kind == "concept_map":
            from .concept_map import render_concept_map
            _RENDERERS[kind] = render_concept_map
        elif kind == "none":
            from .none import render_none
            _RENDERERS[kind] = render_none
        else:
            raise ValueError(f"Unknown renderer kind: {kind}")
    except ImportError as e:
        raise ImportError(f"Renderer '{kind}' requires: {e}")
    
    return _RENDERERS[kind]


def get_renderer(kind: str):
    """Get a renderer function by kind."""
    return _load_renderer(kind)


def register(kind: str):
    """Decorator to register a renderer function (used by renderer modules)."""
    def decorator(func):
        _RENDERERS[kind] = func
        _LOADED.add(kind)
        return func
    return decorator


def render_networkx_graph(content: str, data: dict, kind: str = "diagram") -> str:
    """Shared networkx graph renderer for diagram and concept_map.
    
    Args:
        content: Title text
        data: Dict with 'nodes' and 'edges' lists
        kind: Output filename prefix ('diagram' or 'concept_map')
    
    Returns:
        Path to rendered PNG
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    
    try:
        import networkx as nx
    except ImportError:
        raise ImportError("networkx is required for graph rendering")
    
    G = nx.DiGraph()
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    
    for node in nodes:
        if isinstance(node, dict):
            G.add_node(node["id"], label=node.get("label", node["id"]))
        else:
            G.add_node(node, label=str(node))
    
    for edge in edges:
        if isinstance(edge, dict):
            G.add_edge(edge["from"], edge["to"], label=edge.get("label", ""))
        else:
            G.add_edge(edge[0], edge[1])
    
    fig, ax = plt.subplots(1, 1, figsize=(IMAGE_WIDTH/DPI, IMAGE_HEIGHT/DPI), dpi=DPI)
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    ax.axis("off")
    
    lang = data.get("lang", "en")
    font = get_font_family(lang)

    ax.set_title(content[:50], fontsize=32, fontweight="bold",
                 color=TITLE_COLOR, pad=20, fontfamily=font)
    
    pos = nx.spring_layout(G, k=2.5, iterations=80)
    node_colors = [ACCENT_COLORS[i % len(ACCENT_COLORS)] for i in range(len(G.nodes))]
    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=3000, ax=ax)
    nx.draw_networkx_edges(G, pos, edge_color="#666666", arrows=True,
                          arrowsize=25, connectionstyle="arc3,rad=0.1", ax=ax,
                          width=2.5)
    
    labels = nx.get_node_attributes(G, "label")
    nx.draw_networkx_labels(G, pos, labels, font_size=14, font_color="white",
                           font_weight="bold", ax=ax)
    
    edge_labels = nx.get_edge_attributes(G, "label")
    if edge_labels:
        nx.draw_networkx_edge_labels(G, pos, edge_labels, font_size=11, ax=ax)
    
    plt.subplots_adjust(left=0.05, right=0.95, top=0.90, bottom=0.05)
    return save_figure(fig, kind)
