"""Free on-device talking-head engine: Wav2Lip on a still portrait.

One implementation of the RenderEngine protocol jobs.py drives — the
default, because it needs no API key and no money. Everything runs on this
machine with CPU PyTorch: the photo's mouth is animated to match the speech,
then a subtle head drift makes the frame read as a person, not a freeze.

The interface is asynchronous (submit/poll) even though the work is local,
so the job machine can report progress while a render runs: submit() spawns
a worker thread and returns a handle; poll() reports its state; download()
moves the finished MP4 into the job's video dir.

Weights are NOT in the repo (~436 MB). Fetch them once with:

    python setup_models.py

Render pipeline details are tuned for a still photo — see the notes on face
detection geometry, paste-back blending and head motion below.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
import torch

from vendor.wav2lip import audio as w2l_audio
from vendor.wav2lip.wav2lip import Wav2Lip

from jobs import EngineUnavailable

ROOT = Path(__file__).resolve().parent
IMAGE_PATH = ROOT / "assets" / "avatar.jpg"
MODELS_DIR = ROOT / "models"
CHECKPOINT = MODELS_DIR / "wav2lip_gan.pth"
FACE_MODEL = MODELS_DIR / "face_detection_yunet.onnx"
SCRATCH_DIR = ROOT / "output" / "wav2lip"

FPS = 25
MEL_STEP = 16
FACE_SIZE = 96          # Wav2Lip is trained at 96x96
BATCH = 64

# Crop geometry — measured against the proportions of the LRS2 crops
# Wav2Lip was trained on: the square is about 2.6 eye-to-mouth distances on
# a side, with the mouth centre 72% of the way down it.
CROP_SCALE = 2.6
MOUTH_AT = 0.72

# Paste-back blend: only the mouth region of the 96x96 prediction is really
# generated, so only an ellipse over the mouth/jaw is blended back, feathered
# hard enough never to reach the crop edge.
MOUTH_CX, MOUTH_CY = 0.50, 0.70     # ellipse centre, as fractions of the crop
MOUTH_RX, MOUTH_RY = 0.40, 0.30     # radii

_model: Wav2Lip | None = None
_mask_cache: dict[tuple[int, int], np.ndarray] = {}

# CPU renders must not overlap, or cores thrash and every render slows down.
_render_lock = threading.Lock()


class _Handle:
    """Opaque prediction handle: mirrors the attributes jobs.py reads."""

    def __init__(self) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.status = "starting"
        self.error: str | None = None
        self.output: str | None = None


def _device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _load_model() -> Wav2Lip:
    global _model
    if _model is None:
        blob = torch.load(str(CHECKPOINT), map_location="cpu", weights_only=False)
        state = {k.replace("module.", ""): v for k, v in blob["state_dict"].items()}
        model = Wav2Lip()
        model.load_state_dict(state)
        _model = model.eval()
    return _model


def _detect_face(image: np.ndarray) -> tuple[int, int, int, int]:
    """One SQUARE face crop for the whole render, placed off the landmarks.

    Wav2Lip is trained on square crops in which the face sits at a fixed
    place (eyes ~1/3 down, mouth ~7/10). Hand it a differently framed crop
    and it still draws the mouth at 70% of the crop — which lands on the
    chin and the face slides around. So measure the face from the eyes and
    the mouth (YuNet gives both for free) and build the square at exactly
    the proportions the model expects.
    """
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
    points = face[4:14].reshape(5, 2)          # YuNet's five landmarks
    eye = (points[0] + points[1]) / 2.0
    mouth = (points[3] + points[4]) / 2.0

    span = float(np.hypot(*(mouth - eye)))     # eye centre to mouth centre
    if span < 4:                               # degenerate landmarks
        span = float(face[3]) / 2.9

    side = CROP_SCALE * span
    cx = float((eye[0] + mouth[0]) / 2.0)
    top = float(mouth[1]) - MOUTH_AT * side

    side = min(side, float(w), float(h))
    x1 = min(max(cx - side / 2.0, 0.0), w - side)
    y1 = min(max(top, 0.0), h - side)
    return int(round(x1)), int(round(y1)), min(w, int(round(x1 + side))), \
        min(h, int(round(y1 + side)))


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
# Head motion. Wav2Lip animates only the mouth; a slow drift of the whole
# frame reads as a person holding still rather than a freeze frame. Deliber-
# ately subtle, periods mutually incommensurate so it never visibly repeats,
# amplitude following the speech envelope so the head settles when silent.
# ---------------------------------------------------------------------------
ROT_DEG = 1.5          # peak rotation, degrees
SHIFT_X = 0.030        # peak drift as a fraction of face width
SHIFT_Y = 0.020
SCALE_A = 0.010        # peak "lean in"
PERIODS = (5.7, 4.3, 6.9, 8.1)   # seconds; no common multiple


def _speech_envelope(wav_path: str, n_frames: int) -> np.ndarray:
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
    kernel = np.ones(9, dtype=np.float32) / 9.0
    env = np.convolve(env, kernel, mode="same")
    return 0.45 + 0.55 * env          # never fully still, livelier when loud


def _head_motion(frame: np.ndarray, i: int, amp: float,
                 face_w: float) -> np.ndarray:
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
    return cv2.warpAffine(frame, m, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)


def _blend_mask(width: int, height: int) -> np.ndarray:
    cached = _mask_cache.get((width, height))
    if cached is not None:
        return cached
    ys = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    xs = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    radius = np.sqrt(((xs - MOUTH_CX) / MOUTH_RX) ** 2
                     + ((ys - MOUTH_CY) / MOUTH_RY) ** 2)
    mask = np.clip(1.0 - radius, 0.0, 1.0)
    mask = mask * mask * (3.0 - 2.0 * mask)          # smoothstep
    blur = max(5, (int(min(width, height) * 0.09) | 1))
    mask = cv2.GaussianBlur(mask, (blur, blur), 0)
    mask = mask[:, :, None].astype(np.float32)
    _mask_cache[(width, height)] = mask
    return mask


def _colour_match(generated: np.ndarray, original: np.ndarray) -> np.ndarray:
    """Remove the model's global colour shift before blending.

    The top half of the prediction is a reconstruction of the reference
    face, so whatever it differs from the original by up there is exactly
    the shift applied to the mouth too.
    """
    half = max(1, generated.shape[0] // 2)
    offset = (original[:half].reshape(-1, 3).mean(axis=0)
              - generated[:half].reshape(-1, 3).mean(axis=0))
    return np.clip(generated.astype(np.float32) + offset, 0, 255)


def _sharpen(patch: np.ndarray) -> np.ndarray:
    """Mild unsharp mask: Wav2Lip works at 96x96, upscaled mouths arrive
    soft next to a sharp photograph; a light unsharp restores focus."""
    blurred = cv2.GaussianBlur(patch, (0, 0), 1.6)
    return cv2.addWeighted(patch, 1.35, blurred, -0.35, 0)


def _paste_face(frame: np.ndarray, mouth: np.ndarray,
                box: tuple[int, int, int, int]) -> np.ndarray:
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


def _render(audio_path: Path, face_image: Path, final: Path) -> Path:
    """WAV + photo -> talking-head MP4 at `final`. Runs in a worker thread."""
    frame = cv2.imread(str(face_image))
    if frame is None:
        raise ValueError(f"Could not read the portrait at {face_image}")

    x1, y1, x2, y2 = _detect_face(frame)
    face = cv2.resize(frame[y1:y2, x1:x2], (FACE_SIZE, FACE_SIZE))
    chunks = _mel_chunks(str(audio_path))
    envelope = _speech_envelope(str(audio_path), len(chunks))

    device = _device()
    model = _load_model().to(device)

    silent = final.with_name(final.stem + "_silent.mp4")
    writer = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*"mp4v"),
                             FPS, (frame.shape[1], frame.shape[0]))
    try:
        for start in range(0, len(chunks), BATCH):
            batch = chunks[start:start + BATCH]
            imgs = np.stack([face] * len(batch)).astype(np.float32)
            masked = imgs.copy()
            masked[:, FACE_SIZE // 2:] = 0
            img_in = np.concatenate((masked, imgs), axis=3) / 255.0
            mel_in = np.stack(batch)[..., None]

            img_t = torch.FloatTensor(img_in.transpose(0, 3, 1, 2)).to(device)
            mel_t = torch.FloatTensor(mel_in.transpose(0, 3, 1, 2)).to(device)
            with torch.no_grad():
                pred = model(mel_t, img_t)
            pred = pred.cpu().numpy().transpose(0, 2, 3, 1) * 255.0
            for j, mouth in enumerate(pred.astype(np.uint8)):
                out = _paste_face(frame.copy(), mouth, (x1, y1, x2, y2))
                idx = start + j
                out = _head_motion(out, idx,
                                   float(envelope[min(idx, len(envelope) - 1)]),
                                   float(x2 - x1))
                writer.write(out)
    finally:
        writer.release()

    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg_exe = "ffmpeg"

    subprocess.run(
        [ffmpeg_exe, "-y", "-loglevel", "error",
         "-i", str(silent), "-i", str(audio_path),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(final)],
        check=True, capture_output=True,
    )
    silent.unlink(missing_ok=True)
    return final


class Wav2LipEngine:
    """Renders a talking-head video from a photo + WAV, on this machine."""

    name = "wav2lip-local"

    def __init__(self, image_path: Path = IMAGE_PATH,
                 scratch_dir: Path = SCRATCH_DIR) -> None:
        self.image_path = Path(image_path)
        self.scratch_dir = Path(scratch_dir)
        self.scratch_dir.mkdir(parents=True, exist_ok=True)
        self._handles: dict[str, _Handle] = {}
        self._handles_lock = threading.Lock()

    # ------------------------------------------------------------- protocol
    def available(self) -> bool:
        return CHECKPOINT.is_file() and FACE_MODEL.is_file()

    def setup_hint(self) -> str:
        if self.available():
            return ""
        missing = [p.name for p in (CHECKPOINT, FACE_MODEL) if not p.is_file()]
        return (
            "Model weights missing ({}). Run `python setup_models.py` in "
            "avatar-studio (one-time ~436 MB download), then restart the "
            "server.".format(", ".join(missing))
        )

    def submit(self, audio_path: Path, overrides: dict | None = None):
        if not self.available():
            raise EngineUnavailable(self.setup_hint())
        if not self.image_path.is_file():
            raise EngineUnavailable(f"Avatar photo not found at {self.image_path}")

        self._clear_stale_scratch()
        handle = _Handle()
        # The job machine deletes the source WAV as soon as submit() returns,
        # so snapshot it into our own scratch now, before the worker runs.
        audio_copy = self.scratch_dir / f"{handle.id}.wav"
        shutil.copyfile(Path(audio_path), audio_copy)
        with self._handles_lock:
            self._handles[handle.id] = handle
        thread = threading.Thread(
            target=self._worker, args=(handle, audio_copy), daemon=True)
        thread.start()
        return handle

    def poll(self, prediction_id: str) -> _Handle:
        with self._handles_lock:
            handle = self._handles.get(prediction_id)
        if handle is None:
            raise EngineUnavailable("Unknown local render job")
        return handle

    def output_url(self, handle: _Handle) -> str | None:
        return handle.output if handle.status == "succeeded" else None

    def download(self, url: str, dest: Path) -> Path:
        """`url` is a local path from this engine — move it into place."""
        source = Path(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
        with self._handles_lock:
            self._handles.pop(Path(url).stem[:12], None)
        return Path(dest)

    # -------------------------------------------------------------- workers
    def _worker(self, handle: _Handle, audio_path: Path) -> None:
        # One render at a time on CPU; queueing handles just wait here.
        with _render_lock:
            handle.status = "processing"
            try:
                final = _render(audio_path, self.image_path,
                                self.scratch_dir / f"{handle.id}.mp4")
                handle.status = "succeeded"
                handle.output = str(final)
            except Exception as exc:
                handle.status = "failed"
                handle.error = str(exc)
            finally:
                audio_path.unlink(missing_ok=True)   # our scratch copy

    def _clear_stale_scratch(self) -> None:
        """Scratch files whose job never finished (crash, eviction) are orphans."""
        cutoff = time.time() - 3600
        try:
            for p in self.scratch_dir.glob("*.*"):
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
        except OSError:
            pass