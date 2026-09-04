# Avatar prototype

A 2D VTuber-style avatar whose mouth is driven by the audio Mentora already
generates, with procedural head motion, blinking and gaze.

**Self-contained.** It imports nothing from the rest of the repo and nothing
in the repo imports it. No model files, no weights, no build step, no server
beyond a static file server. Delete the folder and Mentora is unchanged.

```bash
cd avatar-prototype
python3 -m http.server 8620
# then open http://localhost:8620
```

## Why the mouth is driven by amplitude and not phonemes

The obvious design is text → phonemes → visemes. We measured the alternative
first: **edge-tts, which generates all of Mentora's narration, now returns only
`SentenceBoundary` events — no per-word timing** — for English, Hindi and Tamil
alike. There is nothing to align against without adding a forced aligner and a
model per language.

Amplitude is also what VTuber software actually does, and it reads
convincingly. Most importantly it is completely language-agnostic, so all
eighteen of Mentora's languages work with no per-language work at all.

Two parameters come out of the audio, not one:

- `mouthOpen` — how far, from smoothed loudness
- `mouthForm` — which shape, from spectral tilt. Sibilants and close vowels put
  energy up high, open vowels put it low, so the ratio gives a wide/narrow axis
  for free. Without it the mouth is a single hole opening and closing.

## What the tuning is worth

Every number in `TUNING` at the top of `driver.js` was arrived at by measuring,
and the comments record what happens when each is wrong. Two mattered most:

**Loudness has to be measured relative to the voice, not against fixed
thresholds.** The first version used a fixed −45..−12 dB window. Real Mentora
narration is heavily compressed and sits near −16 dB RMS almost continuously,
so the mouth held a mean of 0.87 and *never fully closed* — the slack-jawed
look the silence gate exists to prevent. It now follows a running peak with a
fast rise and a slow decay, which self-calibrates to any voice or backend.

**Loudness in dB is not how far a jaw drops.** Straight off the normalised
level, narration sat wide open for 41% of frames and read as shouting.
`openCurve` bends the response so the ordinary middle of speech comes down
while silence stays shut and an emphatic syllable still reaches full. Measured
across three sections of a 2-minute Hindi narration afterwards: mouth closed
for 9%, 58% and 67% of frames, opening on emphasis.

Two smaller things that matter more than they look: the mouth **opens faster
than it closes** (a symmetric smooth reads as dubbed), and the **eyes reach a
gaze target well before the head does** (reversing that is uncanny in a way
that is hard to name and easy to see).

## Files

| File | What it is |
|---|---|
| `driver.js` | Audio → parameters. Knows nothing about drawing. The part worth keeping |
| `character.js` | Renders those parameters onto the SVG, and wires up the page |
| `index.html` | The page, and the placeholder character as inline SVG |
| `style.css` | Mentora's palette, so it reads as part of the app |

## Swapping in a real model

The SVG character is a **placeholder** — it exists so the driver can be judged
without waiting on art. `driver.js` does not know it exists.

To move to Live2D, write one file exposing the same single function:

```js
setParams({ mouthOpen, mouthForm, eyeOpen, eyeX, eyeY,
            angleX, angleY, angleZ, breath, brow })
```

and have it call, on a `pixi-live2d-display` model:

```js
const core = model.internalModel.coreModel;
core.setParameterValueById("ParamMouthOpenY", p.mouthOpen);
core.setParameterValueById("ParamMouthForm",  p.mouthForm);
core.setParameterValueById("ParamAngleX",     p.angleX);
core.setParameterValueById("ParamEyeLOpen",   p.eyeOpen);
core.setParameterValueById("ParamEyeBallX",   p.eyeX);
core.setParameterValueById("ParamBreath",     p.breath);
```

The parameter names above are deliberately Live2D's own, so that adapter is
close to a straight mapping. `driver.js` does not change at all. Rive or a
hand-rigged PixiJS character would be the same shape of adapter.

**Licensing, before anyone commits to it:** the Live2D Cubism SDK is free for
small-scale and non-commercial use but requires accepting their licence, and
the free sample models carry their own conditions. Read both before shipping.
Rive and a hand-rigged character avoid the question entirely.

## What this replaces, if it is adopted

The whole server-side avatar path: `local_avatar/`, Wav2Lip, the 436MB of
weights, torch's 536MB, and roughly 18 seconds of render per segment. The
avatar becomes client-side and free.

`compose()` and `stitch()` would still be needed for the lesson-video
deliverable — or screen-record the app, which is simpler.

The teaching visual behind the avatar is deliberately NOT part of this branch.
It was prototyped here and taken back out: this branch is the avatar and
nothing else.

## Known limits

- Both placeholder characters are placeholders. They exist so the driver
  could be judged without waiting on art, and are meant to be replaced.
- Head motion is procedural, not learned. It idles convincingly and reacts to
  speech energy, but it does not gesture in time with meaning.
- `mouthForm` is spectral tilt, not real visemes. It varies with the sound
  being made, which is enough to stop the mouth looking mechanical, but it will
  not match a specific consonant.
- `requestAnimationFrame` stops in a hidden tab, so the avatar freezes while
  audio continues, and catches up when the tab is shown. That is the right
  behaviour for battery, but worth knowing before debugging it.
