"""Live 2D-avatar stage for a segment board video (client-side overlay).

SUPERSEDED — nothing calls this, and nothing should.

The teacher is rendered INTO the board video now, by avatar-prototype/
avatar_render.py from encode(). An HTML overlay on top of that would be a
second copy of her, and being absolutely positioned bottom-right it covered
the video element's own fullscreen button. Burnt-in also survives fullscreen,
download and upload, none of which an overlay does.

Kept for reference because the parameter mapping here is the browser-side
mirror of the rig; delete it once nothing needs that reference.


Builds one self-contained HTML block: the narrated board video plus the
approved 2D SVG teacher standing bottom-right, whose mouth is driven by the
video's own audio through avatar-prototype's amplitude driver -- the pattern
proven in avatar-prototype/index.html. The avatar-prototype assets are
inlined at call time, so no static-file server or extra request is needed and
the lesson page keeps working offline.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

_AP = Path(__file__).resolve().parent / "avatar-prototype"


def _video_data_uri(path) -> str:
    return "data:video/mp4;base64," + base64.b64encode(
        Path(path).read_bytes()).decode()


def stage_html(video_path, max_mb=8.0) -> str:
    """HTML for st.components.v1.html: the board video with the live teacher.

    Returns "" when the video is unusable or the avatar assets are missing, so
    the caller falls back to a plain video element.
    """
    path = Path(video_path)
    if not path.exists() or path.stat().st_size <= 0:
        return ""
    if path.stat().st_size > max_mb * 1024 * 1024:
        return ""
    index = (_AP / "index.html").read_text(encoding="utf-8")
    svg = re.search(r'<svg id="avatar".*?</svg>', index, re.S)
    if not svg or not (_AP / "driver.js").exists():
        return ""
    driver = (_AP / "driver.js").read_text(encoding="utf-8")
    return _build(svg.group(0), driver, _video_data_uri(path))


def _build(svg: str, driver_src: str, video_uri: str) -> str:
    driver_src = driver_src.replace("export class AvatarDriver",
                                    "class AvatarDriver")
    driver_src = driver_src.replace("export { TUNING };",
                                    "// TUNING inlined")
    css = (
        ".mentora-stage{position:relative;width:100%;aspect-ratio:16/9;"
        "background:#F5F1E8;overflow:hidden;border-radius:14px;"
        "box-shadow:0 6px 0 rgba(18,16,14,.14)}"
        ".mentora-stage video{position:absolute;inset:0;width:100%;"
        "height:100%;object-fit:cover}"
        ".mentora-stage svg{position:absolute;right:1.5%;bottom:0;"
        "width:18%;height:auto;"
        "filter:drop-shadow(5px 5px 0 rgba(18,16,14,.30))}"
        "#avatar[data-variant=f] .v-m,#avatar[data-variant=m] .v-f{"
        "display:none}"
        ".mentora-hint{margin:8px 0 0;font:13px/1.4 system-ui;color:#666}"
    )
    return (
        '<!doctype html><meta charset="utf-8"><style>' + css + "</style>"
        '<div class="mentora-stage"><video id="boardVideo" src="'
        + video_uri + '" controls playsinline preload="metadata"></video>'
        + svg + "</div>"
        '<p class="mentora-hint">Press play — the teacher lip-syncs to the '
        "narration.</p>"
        + "<script>" + driver_src + "</script><script>" + _EMBED
        + "</script>"
    )


# Mirror of character.js's setParams + page wiring, written against the same
# element ids so it cannot drift from the rig. If character.js changes these
# transforms, update this block to match.
_EMBED = r'''
(function(){
var $ = function(id){ return document.getElementById(id); };
var el = { root: $('root'), head: $('head'), features: $('features'),
  hairBack: $('hairBack'), hairFront: $('hairFront'), body: $('body'),
  eyeL: $('eyeL'), eyeR: $('eyeR'), irisL: $('irisL'), irisR: $('irisR'),
  brows: $('brows'), blush: $('blush'), cavity: $('mouthCavity'),
  tongue: $('mouthTongue'), line: $('mouthLine'), svg: $('avatar') };
var PX = { f: {hairBack:4, head:10, hairFront:14, features:17},
           m: {hairBack:9, head:10, hairFront:11, features:17} };
var LIP = 0.18;
function lerp(a,b,t){ return a + (b - a) * t; }
function setParams(p){
  var ax = p.angleX/26, ay = p.angleY/18,
      px = PX[el.svg.dataset.variant] || PX.f;
  el.root.setAttribute('transform',
    'rotate(' + p.angleZ.toFixed(2) + ' 200 300)');
  el.hairBack.setAttribute('transform',
    'translate(' + (ax*px.hairBack) + ' ' + (ay*px.hairBack*.8) + ')');
  el.hairFront.setAttribute('transform',
    'translate(' + (ax*px.hairFront) + ' ' + (ay*px.hairFront*.7) + ')');
  var sq = 1 - Math.abs(ax) * 0.05;
  el.head.setAttribute('transform',
    'translate(' + (ax*px.head) + ' ' + (ay*px.head*.7) + ')' +
    ' translate(200 220) scale(' + sq.toFixed(3) + ' 1) translate(-200 -220)');
  el.features.setAttribute('transform',
    'translate(' + (ax*px.features) + ' ' + (ay*px.features*.65) + ')');
  el.body.setAttribute('transform',
    'translate(0 ' + ((1 - p.breath) * 2.5) + ')');
  var lid = Math.max(p.eyeOpen, 0.02).toFixed(3);
  el.eyeL.setAttribute('transform',
    'translate(158 222) scale(1 ' + lid + ') translate(-158 -222)');
  el.eyeR.setAttribute('transform',
    'translate(242 222) scale(1 ' + lid + ') translate(-242 -222)');
  var gx = (p.eyeX * 7).toFixed(2), gy = (p.eyeY * 5).toFixed(2);
  el.irisL.setAttribute('transform', 'translate(' + gx + ' ' + gy + ')');
  el.irisR.setAttribute('transform', 'translate(' + gx + ' ' + gy + ')');
  el.brows.setAttribute('transform',
    'translate(0 ' + (-p.brow * 5).toFixed(2) + ')');
  el.blush.setAttribute('opacity', (p.brow * 0.9).toFixed(3));
  var rx = lerp(24, 13, p.mouthForm), ry = 2 + p.mouthOpen * 24;
  el.cavity.setAttribute('rx', rx.toFixed(2));
  el.cavity.setAttribute('ry', ry.toFixed(2));
  el.tongue.setAttribute('rx', (rx * 0.62).toFixed(2));
  el.tongue.setAttribute('ry',
    Math.max(0, p.mouthOpen * 11 - 2).toFixed(2));
  el.tongue.setAttribute('cy', (294 + p.mouthOpen * 7).toFixed(2));
  var seam = Math.max(0, 1 - p.mouthOpen / LIP);
  el.line.setAttribute('opacity', (0.8 * seam).toFixed(3));
}
var driver = new AvatarDriver();
var video = $('boardVideo'), started = false;
function frame(now){
  var p = driver.update(now);
  setParams(p);
  // Browsers may suspend the AudioContext until a user gesture; keep asking
  // until they grant it (the play click is the gesture that unblocks it).
  if (driver.ctx && driver.ctx.state === 'suspended') {
    driver.ctx.resume().catch(function(){});
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
function startAvatar(){
  if (started) return;
  started = true;
  try { driver.attachElement(video); } catch (e) { started = false; }
}
// Native <video controls> live in the shadow DOM, so a click on the play
// button does NOT dispatch a click event on the element itself. Watch the
// whole document in capture phase and test the event's composed path.
document.addEventListener('pointerdown', function(e){
  var path = e.composedPath ? e.composedPath() : [];
  if (path.indexOf(video) !== -1) startAvatar();
}, true);
document.addEventListener('pointerup', function(e){
  var path = e.composedPath ? e.composedPath() : [];
  if (path.indexOf(video) !== -1) startAvatar();
}, true);
video.addEventListener('play', startAvatar);
video.addEventListener('click', startAvatar);
window.__stage = { driver: driver, setParams: setParams, start: startAvatar };
})();
'''


if __name__ == "__main__":
    import sys
    out = stage_html(sys.argv[1]) if len(sys.argv) > 1 else ""
    print(len(out), "chars" if out else "usage: lesson_stage.py <mp4>")
