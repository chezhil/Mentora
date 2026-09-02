"""Demo script for the media pipeline.

Shows how to use render(), choose_visual(), speak(), and compose().
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from media_pipeline import render, choose_visual, speak, compose, stitch


def demo_choose_visual():
    """Demonstrate choose_visual() decision logic."""
    print("\n=== choose_visual() Demo ===\n")
    
    test_cases = [
        ("Ohm's Law", "physics"),
        ("quadratic functions", "maths"),
        ("French Revolution", "history"),
        ("bubble sort algorithm", "programming"),
        ("cell structure", "biology"),
        ("RC circuits", "physics"),
        ("Pythagorean theorem", "maths"),
        ("World War II", "history"),
    ]
    
    for concept, subject in test_cases:
        kind = choose_visual(concept, subject)
        print(f"  {concept:30} ({subject:15}) -> {kind}")


def demo_render():
    """Demonstrate render() for all 7 visual kinds."""
    print("\n=== render() Demo ===\n")
    
    test_cases = [
        ("equation", "E = mc^2\nEnergy equals mass times\nthe speed of light squared"),
        ("graph", "sine wave", {"function": "np.sin(x)", "x_min": -3.14, "x_max": 3.14}),
        ("diagram", "Simple Process", {"boxes": [
            {"x": 2, "y": 5, "label": "Input", "color": "#667eea"},
            {"x": 5, "y": 5, "label": "Process", "color": "#764ba2"},
            {"x": 8, "y": 5, "label": "Output", "color": "#43b581"},
        ]}),
        ("timeline", "Key Events", {"events": [
            {"year": "1969", "label": "Moon Landing"},
            {"year": "1991", "label": "World Wide Web"},
            {"year": "2007", "label": "iPhone Launch"},
        ]}),
        ("code", "def hello():\n    print('Hello, World!')\n\nhello()", {"language": "python", "title": "hello.py"}),
        ("concept_map", "Machine Learning", {"central": "ML", "related": ["Supervised", "Unsupervised", "Reinforcement", "Deep Learning"]}),
        ("none", "Introduction to the Course"),
    ]
    
    for kind, content, *data in test_cases:
        data = data[0] if data else {}
        path = render(kind, content, data=data)
        print(f"  {kind:15} -> {path}")


def demo_speak():
    """Demonstrate speak() with caching."""
    print("\n=== speak() Demo ===\n")
    
    text = "Ohm's law states that voltage equals current times resistance."
    lang = "en"
    
    # First call - generates audio
    path1 = speak(text, lang)
    print(f"  First call:  {path1}")
    
    # Second call - returns cached version
    path2 = speak(text, lang)
    print(f"  Second call: {path2}")
    print(f"  Same file?   {path1 == path2}")


def main():
    """Run all demos."""
    print("Media Pipeline Demo")
    print("=" * 50)
    
    demo_choose_visual()
    demo_render()
    demo_speak()
    
    print("\n" + "=" * 50)
    print("Demo complete! Check the output/ directory for generated files.")


if __name__ == "__main__":
    main()
