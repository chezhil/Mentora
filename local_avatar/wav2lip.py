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
            for mouth in pred.astype(np.uint8):
                out = frame.copy()
                out[y1:y2, x1:x2] = cv2.resize(mouth, (x2 - x1, y2 - y1))
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
