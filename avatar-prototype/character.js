/* Rendering backend: parameters -> this SVG character.
 *
 * SWAPPING IN A REAL MODEL
 * ------------------------
 * Nothing above this file knows what a character looks like. To move to
 * Live2D, write one more file that exposes the same single function —
 *
 *     setParams({ mouthOpen, mouthForm, eyeOpen, eyeX, eyeY,
 *                 angleX, angleY, angleZ, breath, brow })
 *
 * — and have it call, on a pixi-live2d-display model:
 *
 *     const core = model.internalModel.coreModel;
 *     core.setParameterValueById("ParamMouthOpenY", p.mouthOpen);
 *     core.setParameterValueById("ParamMouthForm",  p.mouthForm);
 *     core.setParameterValueById("ParamAngleX",     p.angleX);
 *     ... and so on.
 *
 * The parameter names above are deliberately Live2D's own, so that adapter is
 * close to a straight mapping. driver.js does not change at all.
 */

import { AvatarDriver } from "./driver.js";

const $ = (id) => document.getElementById(id);
const lerp = (a, b, t) => a + (b - a) * t;

const el = {
  root: $("root"), head: $("head"), features: $("features"),
  hairBack: $("hairBack"), hairFront: $("hairFront"), body: $("body"),
  eyeL: $("eyeL"), eyeR: $("eyeR"), irisL: $("irisL"), irisR: $("irisR"),
  brows: $("brows"), blush: $("blush"),
  cavity: $("mouthCavity"), tongue: $("mouthTongue"), line: $("mouthLine"),
};

/* The parallax table. Layers further from the viewer move LESS when the head
 * turns; the features slide furthest because they are travelling across the
 * curve of the face. Getting these four numbers into proportion is the whole
 * illusion — with everything on the same offset the head just slides
 * sideways, which reads as a sticker being dragged rather than a head. */
const PARALLAX = { hairBack: 4, head: 10, hairFront: 14, features: 17 };

/* The lip line is the seam between closed lips, so it has to be gone almost as
 * soon as they part. It was fading linearly with mouthOpen, which left it at
 * 40% opacity with the mouth half open — a line drawn straight across the
 * opening. Gone by this much open instead. */
const LIP_SEAM_GONE_AT = 0.18;

function setParams(p) {
  const ax = p.angleX / 26;             // -1 .. 1
  const ay = p.angleY / 18;

  el.root.setAttribute(
    "transform", `rotate(${p.angleZ.toFixed(2)} 200 300)`);

  el.hairBack.setAttribute("transform",
    `translate(${ax * PARALLAX.hairBack} ${ay * PARALLAX.hairBack * .8})`);
  el.hairFront.setAttribute("transform",
    `translate(${ax * PARALLAX.hairFront} ${ay * PARALLAX.hairFront * .7})`);

  // The face narrows very slightly as it turns away. Small, but without it
  // the head reads as flat card stock.
  const squash = 1 - Math.abs(ax) * 0.05;
  el.head.setAttribute("transform",
    `translate(${ax * PARALLAX.head} ${ay * PARALLAX.head * .7}) ` +
    `translate(200 220) scale(${squash.toFixed(3)} 1) translate(-200 -220)`);
  el.features.setAttribute("transform",
    `translate(${ax * PARALLAX.features} ${ay * PARALLAX.features * .65})`);

  el.body.setAttribute("transform", `translate(0 ${(1 - p.breath) * 2.5})`);

  // Blink by flattening the eye about its own centre.
  const lid = Math.max(p.eyeOpen, 0.02).toFixed(3);
  el.eyeL.setAttribute("transform",
    `translate(158 222) scale(1 ${lid}) translate(-158 -222)`);
  el.eyeR.setAttribute("transform",
    `translate(242 222) scale(1 ${lid}) translate(-242 -222)`);

  const gx = (p.eyeX * 7).toFixed(2), gy = (p.eyeY * 5).toFixed(2);
  el.irisL.setAttribute("transform", `translate(${gx} ${gy})`);
  el.irisR.setAttribute("transform", `translate(${gx} ${gy})`);

  el.brows.setAttribute("transform", `translate(0 ${(-p.brow * 5).toFixed(2)})`);
  el.blush.setAttribute("opacity", (p.brow * 0.9).toFixed(3));

  // mouthForm picks the shape (round -> wide), mouthOpen the size.
  const rx = lerp(24, 13, p.mouthForm);
  const ry = 2 + p.mouthOpen * 24;
  el.cavity.setAttribute("rx", rx.toFixed(2));
  el.cavity.setAttribute("ry", ry.toFixed(2));
  el.tongue.setAttribute("rx", (rx * 0.62).toFixed(2));
  el.tongue.setAttribute("ry", Math.max(0, p.mouthOpen * 11 - 2).toFixed(2));
  el.tongue.setAttribute("cy", (294 + p.mouthOpen * 7).toFixed(2));
  const seam = Math.max(0, 1 - p.mouthOpen / LIP_SEAM_GONE_AT);
  el.line.setAttribute("opacity", (0.8 * seam).toFixed(3));
}

// ---------------------------------------------------------------------------

const driver = new AvatarDriver();
const meters = {
  open: [$("vOpen"), $("bOpen")], form: [$("vForm"), $("bForm")],
  level: [$("vLevel"), $("bLevel")], angle: [$("vAngle"), null],
};

function meter([text, bar], value, digits = 2) {
  text.textContent = value.toFixed(digits);
  if (bar) bar.style.width = `${Math.min(Math.abs(value), 1) * 100}%`;
}

function frame(now) {
  const p = driver.update(now);
  setParams(p);
  meter(meters.open, p.mouthOpen);
  meter(meters.form, p.mouthForm);
  meter(meters.level, p.level);
  meter(meters.angle, p.angleX, 1);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// Debug hook. Handy from the console for tuning without touching the file:
//   __avatar.driver.attachElement(document.querySelector("audio"))
//   __avatar.setParams({mouthOpen: 1, mouthForm: 0, eyeOpen: 1, eyeX: 0,
//                       eyeY: 0, angleX: 20, angleY: 0, angleZ: 0,
//                       breath: 0, brow: 0})
window.__avatar = { driver, setParams };

// --- gaze ------------------------------------------------------------------
const stage = document.querySelector(".stage");
function track(clientX, clientY) {
  const r = stage.getBoundingClientRect();
  driver.lookAt(((clientX - r.left) / r.width - 0.5) * 2,
                ((clientY - r.top) / r.height - 0.5) * 2);
}
stage.addEventListener("pointermove", (e) => track(e.clientX, e.clientY));
stage.addEventListener("pointerleave", () => driver.lookAt(0, 0));

// --- audio sources ---------------------------------------------------------
// Both handlers are user gestures, which is what lets the AudioContext start.
// A browser will not allow it any other way, and an avatar that is silent
// until the first click is the single commonest bug in this kind of page.
const player = $("player");

$("file").addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;
  player.src = URL.createObjectURL(file);
  driver.attachElement(player);
  player.play();
});

// The variant switch is presentation only — it changes which paths are
// visible and nothing else. driver.js is not even aware there are two.
const svg = $("avatar");
$("variant").addEventListener("click", () => {
  svg.dataset.variant = svg.dataset.variant === "f" ? "m" : "f";
});

$("mic").addEventListener("click", async (e) => {
  try {
    await driver.attachMicrophone();
    e.target.textContent = "Listening — talk to it";
    e.target.classList.add("live");
  } catch (err) {
    e.target.textContent = `Microphone blocked (${err.name})`;
  }
});
