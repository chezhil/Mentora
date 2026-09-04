"""Wav2Lip inference against a single still portrait.

Weights are NOT in the repo (436MB). Fetch once:

    curl -sL -o models/wav2lip_gan.pth \
      https://huggingface.co/camenduru/Wav2Lip/resolve/main/checkpoints/wav2lip_gan.pth
    curl -sL -o models/face_detection_yunet.onnx \
      https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx

Notes for whoever maintains this:

  - Face detection uses OpenCV's YuNet, not Wav2Lip's s3fd. s3fd's weights are
    404 on every mirror I tried, and YuNet is 230KB, ships from the OpenCV zoo
    and needs no extra dependency.
  - The source is one still image, so the face box is detected ONCE and every
    frame reuses it. That is why this is fast enough on a laptop.
  - Device order is MPS, then CUDA, then CPU, falling back on any failure —
    the team is on macOS, Windows and Arch.
"""

from __future__ import annotations

import hashlib
import math
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np
import torch

from vendor.wav2lip import audio as w2l_audio
from vendor.wav2lip.wav2lip import Wav2Lip

ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT = ROOT / "models" / "wav2lip_gan.pth"
FACE_MODEL = ROOT / "models" / "face_detection_yunet.onnx"
OUT_DIR = ROOT / "out" / "avatar"

FPS = 25
MEL_STEP = 16
FACE_SIZE = 96          # Wav2Lip is trained at 96x96
BATCH = 64

# Crop geometry — see _detect_face. Measured against the proportions of the
# LRS2 crops Wav2Lip was trained on: the square is about 2.6 eye-to-mouth
# distances on a side, with the mouth centre 72% of the way down it.
CROP_SCALE = 2.6
MOUTH_AT = 0.72

# Paste-back blend. The model returns the whole 96x96 face but only the mouth
# is really generated; everything else is its reconstruction of the input,
# softer and slightly off-colour. So only an ellipse over the mouth and jaw is
# blended back, and it is feathered hard enough never to reach the crop edge.
#
# A rectangular mask was tried first and left a bright vertical band down each
# cheek exactly where the crop edge fell — the mask ramp made the model's
# colour shift into a visible stripe.
MOUTH_CX, MOUTH_CY = 0.50, 0.70     # ellipse centre, as fractions of the crop
MOUTH_RX, MOUTH_RY = 0.40, 0.30     # radii

_model = None


def available() -> bool:
    """True when both weight files are present."""
    return CHECKPOINT.is_file() and FACE_MODEL.is_file()


def _device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _load_model(device: torch.device) -> Wav2Lip:
    global _model
    if _model is None:
        blob = torch.load(str(CHECKPOINT), map_location="cpu", weights_only=False)
        state = {k.replace("module.", ""): v for k, v in blob["state_dict"].items()}
        model = Wav2Lip()
        model.load_state_dict(state)
        _model = model.eval()
    return _model.to(device)


def _face_box_override() -> tuple[int, int, int, int] | None:
    """MENTORA_FACE_BOX="x1,y1,x2,y2" skips detection.

    Two real uses: a stylised or illustrated avatar that no detector will
    register, and a photo where detection picks the wrong face.
    """
    raw = os.environ.get("MENTORA_FACE_BOX", "").strip()
    if not raw:
        return None
    try:
        x1, y1, x2, y2 = (int(v) for v in raw.split(","))
        return x1, y1, x2, y2
    except ValueError:
        raise ValueError(
            f'MENTORA_FACE_BOX must be "x1,y1,x2,y2", got {raw!r}'
        ) from None


def _detect_face(image: np.ndarray) -> tuple[int, int, int, int]:
    """One SQUARE face crop for the whole render, placed off the landmarks.

    This is the single thing that decides whether the lips look attached to
    the face, so it is worth the detail.

    Wav2Lip is trained on square crops in which the face sits at a fixed
    place: eyes about a third of the way down, mouth about seven tenths.
    Everything it generates is drawn at those coordinates. Hand it a crop
    framed differently and it still draws a mouth at 70% of the crop — which
    lands on the chin, or on the nose, and the whole face reads as sliding
    around.

    The previous version padded the detector box by 25% horizontally and 35%
    vertically and resized that to 96x96. On assets/teacher.jpg that produced
    a 267x429 crop — squashed 1.6x vertically into a square, with the mouth at
    62% instead of 70%. Hence lips that neither line up nor move like a mouth.

    So: measure the face from the eyes and the mouth, which is what YuNet
    gives us for free, and build a square crop around them at the proportions
    the model expects.
    """
    override = _face_box_override()
    if override:
        return override

    h, w = image.shape[:2]
    detector = cv2.FaceDetectorYN.create(str(FACE_MODEL), "", (w, h),
                                         score_threshold=0.6)
    detector.setInputSize((w, h))
    _, faces = detector.detect(image)
    if faces is None or len(faces) == 0:
        raise ValueError(
            "No face found in the portrait. Wav2Lip needs a real, "
            "front-facing photograph — a drawn or stylised avatar will not "
            "register."
        )

    # Biggest face, in case the photo has someone in the background.
    face = max(faces, key=lambda f: float(f[2]) * float(f[3]))
    fx, fy, fw, fh = face[:4]
    # YuNet's five landmarks: right eye, left eye, nose, right mouth corner,
    # left mouth corner.
    points = face[4:14].reshape(5, 2)
    eye = (points[0] + points[1]) / 2.0
    mouth = (points[3] + points[4]) / 2.0

    span = float(np.hypot(*(mouth - eye)))          # eye centre to mouth centre
    if span < 4:                                     # degenerate landmarks
        span = float(fh) / 2.9

    side = CROP_SCALE * span
    cx = float((eye[0] + mouth[0]) / 2.0)
    top = float(mouth[1]) - MOUTH_AT * side

    # Keep it square and inside the image: shrink first, then slide.
    side = min(side, float(w), float(h))
    x1 = cx - side / 2.0
    y1 = top
    x1 = min(max(x1, 0.0), w - side)
    y1 = min(max(y1, 0.0), h - side)

    x1, y1 = int(round(x1)), int(round(y1))
    edge = int(round(side))
    return x1, y1, min(w, x1 + edge), min(h, y1 + edge)


def _mel_chunks(wav_path: str) -> list[np.ndarray]:
    wav = w2l_audio.load_wav(wav_path, 16000)
    mel = w2l_audio.melspectrogram(wav)
    if np.isnan(mel.reshape(-1)).sum() > 0:
        raise ValueError("Mel spectrogram contains NaN — is the WAV silent?")

    # Wav2Lip wants a mel window MEL_STEP wide. Under about 0.2s of audio the
    # spectrogram is narrower than that, and the loop below then slices
    # mel[:, shape[1] - MEL_STEP:] with a NEGATIVE start, which wraps and
    # yields a window of the wrong width -- (80, 5) for a tenth of a second.
    # The model rejects it with "Calculated padded input size per channel:
    # (3 x 2). Kernel size: (3 x 3)", so the whole avatar render fails.
    # The orchestrator catches that, so the lesson survives and just quietly
    # loses its teacher for the segment. Pad to one full window instead.
    if mel.shape[1] < MEL_STEP:
        mel = np.pad(mel, ((0, 0), (0, MEL_STEP - mel.shape[1])), mode="edge")

    chunks, i, step = [], 0, 80.0 / FPS
    while True:
        start = int(i * step)
        if start + MEL_STEP > mel.shape[1]:
            chunks.append(mel[:, mel.shape[1] - MEL_STEP:])
            break
        chunks.append(mel[:, start:start + MEL_STEP])
        i += 1
    return chunks


# ---------------------------------------------------------------------------
# Synthetic head motion
#
# Wav2Lip animates the mouth and nothing else, so the output is a photograph
# with a moving mouth — technically correct and slightly unsettling. A slow
# drift of the whole frame reads as a person holding still rather than a
# freeze frame.
#
# Deliberately subtle. Anything you consciously notice looks worse than no
# motion at all. The periods are mutually incommensurate so the loop never
# visibly repeats, and the amplitude follows the speech envelope, so the head
# settles when the teacher stops talking.
#
# MENTORA_HEAD_MOTION=0 turns it off.
# ---------------------------------------------------------------------------

# Amplitudes are relative to the FACE, not the frame. Scaling by frame width
# made the motion vanish on a tightly cropped portrait: 0.27% of frame width,
# which measured as movement and read as a freeze frame.
ROT_DEG = 1.5          # peak rotation, degrees
SHIFT_X = 0.030        # peak drift as a fraction of face width
SHIFT_Y = 0.020
SCALE_A = 0.010        # peak "lean in"
PERIODS = (5.7, 4.3, 6.9, 8.1)   # seconds; no common multiple


def _speech_envelope(wav_path: str, n_frames: int) -> np.ndarray:
    """Per-frame loudness in 0..1, so motion tracks the voice."""
    try:
        samples = w2l_audio.load_wav(wav_path, 16000)
    except Exception:
        return np.ones(n_frames, dtype=np.float32)

    per_frame = int(16000 / FPS)
    env = np.zeros(n_frames, dtype=np.float32)
    for i in range(n_frames):
        chunk = samples[i * per_frame:(i + 1) * per_frame]
        env[i] = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0
    peak = env.max()
    if peak <= 0:
        return np.ones(n_frames, dtype=np.float32)
    env = env / peak
    # Smooth, or the head jitters on every syllable.
    kernel = np.ones(9, dtype=np.float32) / 9.0
    env = np.convolve(env, kernel, mode="same")
    return 0.45 + 0.55 * env          # never fully still, livelier when loud


def _head_motion(frame: np.ndarray, i: int, amp: float,
                 face_w: float) -> np.ndarray:
    """One slow affine nudge. Cheap: a single warpAffine per frame."""
    t = i / FPS
    h, w = frame.shape[:2]
    k = face_w                         # amplitudes are fractions of the face

    p1, p2, p3, p4 = PERIODS
    angle = ROT_DEG * amp * math.sin(2 * math.pi * t / p1)
    dx = SHIFT_X * k * amp * math.sin(2 * math.pi * t / p2 + 1.1)
    dy = SHIFT_Y * k * amp * math.sin(2 * math.pi * t / p3 + 2.3)
    scale = 1.0 + SCALE_A * amp * math.sin(2 * math.pi * t / p4)

    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    m[0, 2] += dx
    m[1, 2] += dy
    # Replicate the edge instead of leaving black borders as the frame drifts.
    return cv2.warpAffine(frame, m, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)


# ---------------------------------------------------------------------------
# Paste-back
#
# The old code did `frame[y1:y2, x1:x2] = resize(prediction)`, which replaces
# the WHOLE crop with a 96x96 upsample. Two visible costs: the eyes and hair
# inside the box go soft, and the crop edge is a hard rectangular seam that
# the head motion then slides around the frame.
#
# Only the mouth is actually generated, so only the mouth is blended back, on
# a mask that fades in vertically across the nose and out at the sides.
# ---------------------------------------------------------------------------

_MASK_CACHE: dict[tuple[int, int], np.ndarray] = {}


def _blend_mask(width: int, height: int) -> np.ndarray:
    """Feathered ellipse over the mouth and jaw, 0 everywhere else."""
    cached = _MASK_CACHE.get((width, height))
    if cached is not None:
        return cached

    ys = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    xs = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    radius = np.sqrt(((xs - MOUTH_CX) / MOUTH_RX) ** 2
                     + ((ys - MOUTH_CY) / MOUTH_RY) ** 2)

    # 1 inside, falling to 0 at the ellipse edge. Smoothstep so the ramp has
    # no visible start or end.
    mask = np.clip(1.0 - radius, 0.0, 1.0)
    mask = mask * mask * (3.0 - 2.0 * mask)

    blur = max(5, (int(min(width, height) * 0.09) | 1))
    mask = cv2.GaussianBlur(mask, (blur, blur), 0)
    mask = mask[:, :, None].astype(np.float32)
    _MASK_CACHE[(width, height)] = mask
    return mask


def _colour_match(generated: np.ndarray, original: np.ndarray) -> np.ndarray:
    """Remove the model's global colour shift before blending.

    The top half of the prediction is a reconstruction of the unmasked
    reference face, so whatever it differs from the original by up there is
    exactly the shift applied to the mouth as well. Correcting by that
    difference is what stops the blended patch reading as a lighter rectangle.
    """
    half = max(1, generated.shape[0] // 2)
    offset = (original[:half].reshape(-1, 3).mean(axis=0)
              - generated[:half].reshape(-1, 3).mean(axis=0))
    return np.clip(generated.astype(np.float32) + offset, 0, 255)


def _sharpen(patch: np.ndarray) -> np.ndarray:
    """Mild unsharp mask on the generated mouth.

    Wav2Lip works at 96x96 and our crop is 2-3x that, so the mouth arrives
    upscaled and soft next to a sharp photograph. A light unsharp brings it
    back into the same focus without the crunchy halo a stronger one gives.
    """
    blurred = cv2.GaussianBlur(patch, (0, 0), 1.6)
    return cv2.addWeighted(patch, 1.35, blurred, -0.35, 0)


def _paste_face(frame: np.ndarray, mouth: np.ndarray,
                box: tuple[int, int, int, int]) -> np.ndarray:
    """Blend one generated face back into its frame."""
    x1, y1, x2, y2 = box
    width, height = x2 - x1, y2 - y1
    region = frame[y1:y2, x1:x2]

    generated = cv2.resize(mouth, (width, height), interpolation=cv2.INTER_CUBIC)
    generated = _colour_match(generated, region.astype(np.float32))
    generated = _sharpen(generated.astype(np.uint8)).astype(np.float32)

    mask = _blend_mask(width, height)
    merged = generated * mask + region.astype(np.float32) * (1.0 - mask)
    frame[y1:y2, x1:x2] = np.clip(merged, 0, 255).astype(np.uint8)
    return frame


def render_avatar(audio_path: str, face_image: str) -> str:
    """CONTRACT: path to a WAV and a photo, returns a talking-head MP4."""
    if not available():
        raise FileNotFoundError(
            f"Wav2Lip weights missing. Expected {CHECKPOINT} and {FACE_MODEL}. "
            f"See local_avatar/wav2lip.py for the two download commands."
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(
        (Path(audio_path).name + Path(face_image).name +
         str(Path(audio_path).stat().st_size)).encode()
    ).hexdigest()[:12]
    final = OUT_DIR / f"avatar_{key}.mp4"
    if final.exists():                       # cache: renders are the slow part
        return str(final)

    frame = cv2.imread(face_image)
    if frame is None:
        raise ValueError(f"Could not read the portrait at {face_image}")

    x1, y1, x2, y2 = _detect_face(frame)
    face = cv2.resize(frame[y1:y2, x1:x2], (FACE_SIZE, FACE_SIZE))

    chunks = _mel_chunks(audio_path)
    device = _device()
    model = _load_model(device)

    motion_on = os.environ.get("MENTORA_HEAD_MOTION", "1") != "0"
    envelope = _speech_envelope(audio_path, len(chunks)) if motion_on else None

    silent = OUT_DIR / f"silent_{key}.mp4"
    writer = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*"mp4v"),
                             FPS, (frame.shape[1], frame.shape[0]))
    try:
        for start in range(0, len(chunks), BATCH):
            batch = chunks[start:start + BATCH]

            # Wav2Lip takes 6 channels: the face with its lower half masked,
            # concatenated with the unmasked reference face.
            imgs = np.stack([face] * len(batch)).astype(np.float32)
            masked = imgs.copy()
            masked[:, FACE_SIZE // 2:] = 0
            img_in = np.concatenate((masked, imgs), axis=3) / 255.0
            mel_in = np.stack(batch)[..., None]

            img_t = torch.FloatTensor(img_in.transpose(0, 3, 1, 2)).to(device)
            mel_t = torch.FloatTensor(mel_in.transpose(0, 3, 1, 2)).to(device)

            with torch.no_grad():
                pred = model(mel_t, img_t)

            pred = (pred.cpu().numpy().transpose(0, 2, 3, 1) * 255.0)
            for j, mouth in enumerate(pred.astype(np.uint8)):
                out = _paste_face(frame.copy(), mouth, (x1, y1, x2, y2))
                if envelope is not None:
                    idx = start + j
                    out = _head_motion(
                        out, idx,
                        float(envelope[min(idx, len(envelope) - 1)]),
                        float(x2 - x1),
                    )
                writer.write(out)
    finally:
        writer.release()

    # Mux the narration in.
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg_exe = "ffmpeg"

    subprocess.run(
        [ffmpeg_exe, "-y", "-loglevel", "error",
         "-i", str(silent), "-i", audio_path,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(final)],
        check=True, capture_output=True,
    )
    silent.unlink(missing_ok=True)
    return str(final)
