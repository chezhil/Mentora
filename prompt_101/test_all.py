#!/usr/bin/env python3
"""Comprehensive test suite for the media pipeline.

Tests all local functionality (no API keys needed).
Run with: python test_all.py
"""
import sys
import wave
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))


def test_choose_visual():
    """Test choose_visual() rules table."""
    from media_pipeline import choose_visual
    
    tests = [
        ("Ohms Law", "physics", "diagram"),
        ("RC circuits", "physics", "diagram"),
        ("wave motion", "physics", "graph"),
        ("quadratic functions", "maths", "graph"),
        ("Pythagorean theorem", "maths", "equation"),
        ("French Revolution", "history", "timeline"),
        ("cell structure", "biology", "diagram"),
        ("bubble sort", "programming", "code"),
    ]
    
    passed = 0
    failed = 0
    for concept, subject, expected in tests:
        result = choose_visual(concept, subject)
        if result == expected:
            passed += 1
        else:
            print(f"  FAIL: choose_visual({concept!r}, {subject!r}) = {result!r}, expected {expected!r}")
            failed += 1
    
    return passed, failed


def test_render_all_kinds():
    """Test render() for all 7 visual kinds."""
    from media_pipeline import render
    from PIL import Image
    import numpy as np
    
    passed = 0
    failed = 0
    
    for kind in ["equation", "graph", "diagram", "timeline", "code", "concept_map", "none"]:
        try:
            path = render(kind, "Test content", subject="physics")
            img = Image.open(path).convert("RGB")
            
            # Check dimensions
            if img.size != (1280, 720):
                print(f"  FAIL: render({kind}) size={img.size}, expected (1280, 720)")
                failed += 1
                continue
            
            # Check content exists (bounding box)
            arr = np.array(img)
            bg = np.array([248, 249, 250])  # #f8f9fa
            mask = np.any(np.abs(arr.astype(int) - bg) > 20, axis=2)
            
            if mask.any():
                rows = np.any(mask, axis=1)
                cols = np.any(mask, axis=0)
                rmin, rmax = np.where(rows)[0][[0, -1]]
                cmin, cmax = np.where(cols)[0][[0, -1]]
                w_pct = (cmax - cmin) / 1280 * 100
                h_pct = (rmax - rmin) / 720 * 100
                
                if w_pct >= 50 and h_pct >= 50:
                    passed += 1
                else:
                    print(f"  FAIL: render({kind}) content too small: {w_pct:.0f}%x{h_pct:.0f}%")
                    failed += 1
            else:
                print(f"  FAIL: render({kind}) no visible content")
                failed += 1
        except Exception as e:
            print(f"  FAIL: render({kind}) raised {type(e).__name__}: {e}")
            failed += 1
    
    return passed, failed


def test_speak_caching():
    """Test speak() hash caching."""
    from media_pipeline import speak
    
    passed = 0
    failed = 0
    
    try:
        path1 = speak("Test caching sentence.", "en")
        path2 = speak("Test caching sentence.", "en")
        
        if path1 == path2:
            passed += 1
        else:
            print(f"  FAIL: speak() cache mismatch: {path1} != {path2}")
            failed += 1
    except Exception as e:
        print(f"  FAIL: speak() raised {type(e).__name__}: {e}")
        failed += 1
    
    # Test empty text
    try:
        speak("", "en")
        print("  FAIL: speak('') should raise ValueError")
        failed += 1
    except ValueError:
        passed += 1
    
    return passed, failed


def test_compose_stitch():
    """Test compose() and stitch()."""
    from media_pipeline import render, compose, stitch
    
    passed = 0
    failed = 0
    
    # Create test audio
    wav_path = Path("test_audio.wav")
    with wave.open(str(wav_path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(b"\x00\x00" * (44100 * 2))
    
    try:
        # Test compose with visual + audio
        visual = render("equation", "E=mc^2")
        segment = compose(visual, str(wav_path))
        
        if Path(segment).exists() and Path(segment).stat().st_size > 0:
            passed += 1
        else:
            print(f"  FAIL: compose() produced empty file")
            failed += 1
        
        # Test compose with None audio
        segment2 = compose(visual, None)
        if Path(segment2).exists():
            passed += 1
        else:
            print(f"  FAIL: compose(visual, None) failed")
            failed += 1
        
        # Test stitch
        final = stitch([segment, segment2])
        if Path(final).exists() and Path(final).stat().st_size > 0:
            passed += 1
        else:
            print(f"  FAIL: stitch() produced empty file")
            failed += 1
        
        # Test stitch empty
        try:
            stitch([])
            print("  FAIL: stitch([]) should raise ValueError")
            failed += 1
        except ValueError:
            passed += 1
        
    except Exception as e:
        print(f"  FAIL: compose/stitch raised {type(e).__name__}: {e}")
        failed += 1
    finally:
        wav_path.unlink(missing_ok=True)
    
    return passed, failed


def test_avatar_60s_guard():
    """Test render_avatar() 60-second limit."""
    from media_pipeline.avatar import render_avatar
    
    passed = 0
    failed = 0
    
    # Create 65-second WAV
    long_wav = Path("test_long.wav")
    with wave.open(str(long_wav), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(b"\x00\x00" * (44100 * 65))
    
    try:
        render_avatar(str(long_wav), "nonexistent.jpg")
        print("  FAIL: render_avatar(65s) should raise ValueError")
        failed += 1
    except ValueError:
        passed += 1
    finally:
        long_wav.unlink(missing_ok=True)
    
    return passed, failed


def test_config_dataclass():
    """Test PipelineConfig dataclass."""
    from media_pipeline.config import PipelineConfig
    
    passed = 0
    failed = 0
    
    try:
        config = PipelineConfig()
        if config.max_segment_duration == 60:
            passed += 1
        else:
            print(f"  FAIL: PipelineConfig.max_segment_duration = {config.max_segment_duration}")
            failed += 1
        
        if config.image_width == 1280:
            passed += 1
        else:
            print(f"  FAIL: PipelineConfig.image_width = {config.image_width}")
            failed += 1
        
        # Test custom config
        custom = PipelineConfig(tts_provider="google", max_segment_duration=30)
        if custom.tts_provider == "google" and custom.max_segment_duration == 30:
            passed += 1
        else:
            print(f"  FAIL: PipelineConfig custom values not applied")
            failed += 1
        
    except Exception as e:
        print(f"  FAIL: PipelineConfig raised {type(e).__name__}: {e}")
        failed += 1
    
    return passed, failed


def main():
    """Run all tests and print summary."""
    print("=" * 60)
    print("Media Pipeline Test Suite")
    print("=" * 60)
    print()
    
    tests = [
        ("choose_visual()", test_choose_visual),
        ("render() all kinds", test_render_all_kinds),
        ("speak() caching", test_speak_caching),
        ("compose() + stitch()", test_compose_stitch),
        ("render_avatar() 60s guard", test_avatar_60s_guard),
        ("PipelineConfig", test_config_dataclass),
    ]
    
    total_passed = 0
    total_failed = 0
    
    for name, test_fn in tests:
        print(f"Testing {name}...")
        passed, failed = test_fn()
        total_passed += passed
        total_failed += failed
        print(f"  {passed} passed, {failed} failed")
        print()
    
    print("=" * 60)
    print(f"TOTAL: {total_passed} passed, {total_failed} failed")
    print("=" * 60)
    
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
