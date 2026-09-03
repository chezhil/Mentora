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
    """One face box for the whole render — the source is a still photo."""
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
    x, y, fw, fh = faces[0][:4].astype(int)
    # Wav2Lip expects chin and mouth well inside the crop; pad generously and
    # clamp to the image.
    pad_x, pad_y = int(fw * 0.25), int(fh * 0.35)
    x1, y1 = max(0, x - pad_x), max(0, y - pad_y)
    x2, y2 = min(w, x + fw + pad_x), min(h, y + fh + pad_y)
    return x1, y1, x2, y2


def _mel_chunks(wav_path: str) -> list[np.ndarray]:
    wav = w2l_audio.load_wav(wav_path, 16000)
    mel = w2l_audio.melspectrogram(wav)
    if np.isnan(mel.reshape(-1)).sum() > 0:
        raise ValueError("Mel spectrogram contains NaN — is the WAV silent?")

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
                out = frame.copy()
                out[y1:y2, x1:x2] = cv2.resize(mouth, (x2 - x1, y2 - y1))
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
