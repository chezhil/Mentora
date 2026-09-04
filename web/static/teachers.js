/* The teachers: one rig, several people.
 *
 * Everything here is a colour swap on the SVG the lesson videos already use.
 * That is deliberate. The obvious move is a library -- DiceBear has 61 MIT
 * styles -- but those avatars have no mouth rig, and their paths use curve
 * commands our Python renderer does not parse, so a DiceBear teacher would
 * animate in the browser and break in the rendered lesson. A palette works in
 * both, adds no dependency and no download, and keeps the drawing consistent
 * between voice mode and video.
 *
 * Keys are the fills as they appear in the SVG. Anything absent is left alone.
 */
window.MENTORA_TEACHERS = [];

/* Loaded from avatar-prototype/teachers.json via /api/teachers so the browser
 * and the video renderer cannot disagree about who a teacher is. */
window.teachersReady = fetch('/api/teachers')
  .then(function (r) { return r.json(); })
  .then(function (list) { window.MENTORA_TEACHERS = list; return list; })
  .catch(function () { return (window.MENTORA_TEACHERS = []); });

/* Paint one <svg> as the given teacher. Re-applying is safe: the original
 * fill is remembered on the node the first time it is touched, so switching
 * teacher never compounds an earlier swap. */
window.paintTeacher = function (svg, teacher) {
  if (!svg || !teacher) return;
  svg.setAttribute('data-variant', teacher.variant || 'f');
  var palette = teacher.palette || {};
  svg.querySelectorAll('[fill]').forEach(function (node) {
    if (!node.dataset.fill0) node.dataset.fill0 = node.getAttribute('fill');
    var base = node.dataset.fill0;
    node.setAttribute('fill', palette[base] || base);
  });
};

window.teacherById = function (id) {
  var list = window.MENTORA_TEACHERS;
  for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
  return list[0];
};
