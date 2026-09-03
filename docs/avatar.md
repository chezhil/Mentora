# Avatar

`local_avatar/wav2lip.py` — `render_avatar(audio_path, face_image) -> mp4`.

```python
import local_avatar

mp4 = local_avatar.render_avatar("narration.wav", "assets/teacher.jpg")
```

> This file previously documented `freebuff.avatar`, a Replicate-hosted
> LivePortrait call at roughly $0.40 per 60-second render. That path still
> exists in `prompt_101/media_pipeline/avatar.py` and `wiring.py` will fall
> back to it, but it is no longer what runs: Wav2Lip on this machine does the
> same job for nothing. `MENTORA_LOCAL_AVATAR=0` forces the paid path.

## What it does

One still photograph in, one talking head out. The face is detected once and
every frame reuses that box, which is what makes it fast enough on a laptop
(~18s per segment on an M-series Mac, and renders are cached).

Device order is MPS, then CUDA, then CPU.

## The crop is the whole problem

This is the part that decides whether the lips look attached to the face, and
it is worth stating precisely because getting it wrong is not obvious from the
code — only from the output.

Wav2Lip is trained on square crops in which the face sits at a fixed place:
eyes about a third of the way down, mouth about seven tenths. Everything it
generates is drawn at those coordinates. Hand it a crop framed differently and
it still draws a mouth at 70% of the crop — which lands on the chin, or on the
nose, and the face reads as sliding around.

The first version padded YuNet's detector box by 25% horizontally and 35%
vertically and resized the result to 96×96. On `assets/teacher.jpg` that gave
a **267×429** crop — squashed 1.6× vertically into a square, with the mouth at
62% instead of 72%.

It is now built from the landmarks YuNet returns for free:

```
span  = distance(eye centre, mouth centre)
side  = 2.6 * span                     # square
top   = mouth_y - 0.72 * side          # mouth at 72% of the crop
```

which gives a **236×236** square on the same photograph.

## Paste-back

The model returns a whole 96×96 face, but only the mouth is really generated;
the rest is its reconstruction of the input, softer and slightly off-colour.

So only an ellipse over the mouth and jaw is blended back, feathered so it
never reaches the crop edge, after a colour correction measured from the top
half of the prediction (which should equal the original, so whatever it
differs by up there is the shift to remove). The real eyes and hair stay
sharp, and there is no seam.

A rectangular mask was tried first and left a bright vertical band down each
cheek exactly where the crop edge fell — the mask ramp turned the model's
colour shift into a visible stripe.

## Head motion

Wav2Lip animates the mouth and nothing else, so the raw output is a photograph
with a moving mouth: technically correct and slightly unsettling. A slow
affine drift of the whole frame reads as a person holding still instead.

Deliberately subtle — anything you consciously notice looks worse than no
motion. The four periods are mutually incommensurate so the loop never
visibly repeats, and the amplitude follows the speech envelope, so the head
settles when the teacher stops talking. `MENTORA_HEAD_MOTION=0` turns it off.

## Requirements

- A **real, front-facing photograph** at `assets/teacher.jpg`. A drawn or
  stylised avatar will not register with the detector, and `render_avatar`
  raises rather than producing something wrong. `MENTORA_FACE_BOX="x1,y1,x2,y2"`
  skips detection for a stylised face or a photo with two people in it.
- Weights: `models/wav2lip_gan.pth` (436MB) and
  `models/face_detection_yunet.onnx` (230KB). Neither is in git.
  `python setup_assets.py` fetches both.

`local_avatar.available()` reports whether they are present; `wiring.py` falls
back to the placeholder rather than crashing when they are not, and the
sidebar says so.

## The 60-second guard

`shared/config.MAX_AVATAR_SECONDS` caps a segment. Longer narration means a
longer render and a face that drifts, and on the paid path it also means real
money. `teacher/engine.fit_script` trims narration to roughly 85% of that
budget before it ever reaches here, because asking the model nicely was not
enough — with a real key it produced scripts of 74 to 114 seconds and every
segment came back with no video.
