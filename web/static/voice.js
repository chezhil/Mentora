/* Voice mode: talk to the teacher, she talks back.
 *
 * Speech in and speech out both happen HERE, in the browser. The server
 * pipeline that renders a lesson takes 30-60 seconds per turn -- fine for a
 * lesson you sit and watch, useless for a conversation. SpeechRecognition and
 * speechSynthesis answer in the time it takes to think, which is what makes
 * this feel live. The server does the two things the browser cannot: decide
 * what to say, and draw the diagram.
 *
 * The avatar is the same SVG rig the lesson videos use, driven from the
 * synthesiser's own boundary events instead of an audio analyser, because
 * speechSynthesis gives no waveform to measure.
 */
(function () {
  var $ = function (id) { return document.getElementById(id); };

  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var synth = window.speechSynthesis;

  var history = [];          // {role, text}
  var listening = false;     // the user asked to be heard
  var busy = false;          // waiting on the server
  var muted = false;
  var recog = null;
  var lang = 'en-US';
  var voice = null;

  // ---- avatar -------------------------------------------------------------
  var svg = $('avatar');
  var mouthCavity = svg && svg.querySelector('#mouthCavity');
  var mouthLine = svg && svg.querySelector('#mouthLine');
  var head = svg && svg.querySelector('#head');
  var eyeL = svg && svg.querySelector('#eyeL');
  var eyeR = svg && svg.querySelector('#eyeR');

  var openness = 0, target = 0, t0 = performance.now();

  function frame(now) {
    var t = (now - t0) / 1000;
    // Ease toward the target so the jaw has weight instead of snapping.
    openness += (target - openness) * 0.35;

    if (mouthCavity) {
      var ry = 2 + openness * 13;
      mouthCavity.setAttribute('ry', ry.toFixed(2));
      mouthCavity.setAttribute('rx', (24 - openness * 6).toFixed(2));
    }
    // The lip seam fades as the mouth opens; a closed mouth still needs it.
    if (mouthLine) mouthLine.style.opacity = Math.max(0, 1 - openness * 2.2);

    // Idle life: a slow sway, a little more of it while speaking.
    var life = 0.4 + openness * 1.2;
    var sway = Math.sin(t * 0.7) * 2.4 * life;
    var nod = Math.sin(t * 1.3) * 1.4 * life;
    if (head) head.setAttribute('transform',
      'translate(' + sway.toFixed(2) + ',' + nod.toFixed(2) + ')');

    // Blink on a wandering schedule.
    var blink = (t % 4.7) < 0.13 ? 0.08 : 1;
    [eyeL, eyeR].forEach(function (e, i) {
      if (!e) return;
      var cx = i === 0 ? 158 : 242;
      e.setAttribute('transform',
        'translate(0,' + (222 * (1 - blink)).toFixed(2) + ') scale(1,' + blink + ')');
      e.setAttribute('transform-origin', cx + ' 222');
    });

    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  function say(state) { $('state').textContent = state; }

  // ---- transcript ---------------------------------------------------------
  function add(role, text) {
    var empty = $('empty');
    if (empty) empty.remove();
    var el = document.createElement('div');
    el.className = 'turn ' + role;
    el.innerHTML = '<div class="label">' + (role === 'student' ? 'You' : 'Mentora') +
      '</div><p></p>';
    el.querySelector('p').textContent = text;
    $('log').appendChild(el);
    $('log').scrollTop = $('log').scrollHeight;
    history.push({role: role, text: text});
    try {
      sessionStorage.setItem('mentora_voice_log', JSON.stringify(history));
    } catch (e) {}
    return el;
  }

  // ---- speaking -----------------------------------------------------------
  function pickVoice() {
    var all = synth.getVoices();
    if (!all.length) return null;
    var base = lang.split('-')[0];
    var exact = all.filter(function (v) { return v.lang === lang; });
    var loose = all.filter(function (v) { return v.lang.indexOf(base) === 0; });
    var pool = exact.length ? exact : (loose.length ? loose : all);
    // Prefer a natural-sounding one where the platform offers it.
    var nice = pool.filter(function (v) { return /natural|neural|premium|enhanced/i.test(v.name); });
    return (nice[0] || pool[0]);
  }

  function speak(text, done) {
    if (muted || !synth) { target = 0; done(); return; }
    synth.cancel();
    var u = new SpeechSynthesisUtterance(text);
    voice = voice || pickVoice();
    if (voice) { u.voice = voice; u.lang = voice.lang; } else { u.lang = lang; }
    u.rate = 1.0;
    u.pitch = 1.0;

    // Boundary events land on each word, which is enough to drive a jaw:
    // open on the word, fall between them.
    u.onboundary = function () {
      target = 0.55 + Math.random() * 0.45;
      setTimeout(function () { target = 0.12; }, 90);
    };
    u.onstart = function () { say('Speaking'); };
    u.onend = function () { target = 0; done(); };
    u.onerror = function () { target = 0; done(); };
    synth.speak(u);
  }

  // ---- the exchange -------------------------------------------------------
  async function ask(text) {
    if (busy) return;
    busy = true;
    add('student', text);
    say('Thinking');
    $('hint').textContent = 'Thinking…';

    var d;
    try {
      var r = await fetch('/api/voice/reply', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: text, history: history.slice(0, -1)}),
      });
      d = await r.json();
      if (!r.ok) throw new Error(d.error || 'The teacher could not answer.');
    } catch (e) {
      busy = false;
      say('Ready');
      add('teacher', 'Sorry — ' + e.message);
      $('hint').textContent = 'Something went wrong. Try again.';
      if (listening) start();
      return;
    }

    if (d.image) {
      $('board').style.display = 'block';
      $('boardCap').textContent = d.caption || 'On the board';
      $('boardImg').innerHTML = '<img alt="' + (d.caption || 'diagram') + '" src="' + d.image + '">';
    }

    add('teacher', d.answer);
    // Recognition must be off while she talks, or the microphone hears her
    // and answers itself in a loop.
    stopRecog();
    speak(d.answer, function () {
      busy = false;
      say(listening ? 'Listening' : 'Ready');
      $('hint').textContent = listening
        ? 'Listening — just talk.'
        : 'Press Start to talk again.';
      if (listening) start();
    });
  }

  // ---- listening ----------------------------------------------------------
  function start() {
    if (!SR || busy) return;
    stopRecog();
    recog = new SR();
    recog.lang = lang;
    recog.continuous = false;
    recog.interimResults = true;

    var finalText = '';
    recog.onresult = function (e) {
      var interim = '';
      for (var i = e.resultIndex; i < e.results.length; i++) {
        var r = e.results[i];
        if (r.isFinal) finalText += r[0].transcript;
        else interim += r[0].transcript;
      }
      if (interim) say('Hearing: ' + interim.trim().slice(0, 28));
    };
    recog.onerror = function (e) {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        listening = false;
        setTalk(false);
        $('hint').textContent = 'Microphone blocked. Allow it, or type below.';
        say('Mic blocked');
      }
    };
    recog.onend = function () {
      var text = finalText.trim();
      finalText = '';
      if (text) { ask(text); return; }
      // Nothing heard: keep the ear open rather than making them press again.
      if (listening && !busy) start(); else if (!busy) say('Ready');
    };

    try { recog.start(); say('Listening'); } catch (e) {}
  }

  function stopRecog() {
    if (!recog) return;
    try { recog.onend = null; recog.stop(); } catch (e) {}
    recog = null;
  }

  function setTalk(on) {
    $('talk').textContent = on ? 'Listening…' : 'Start talking';
    $('talk').classList.toggle('live', on);
    $('stop').disabled = !on;
  }

  // ---- wiring -------------------------------------------------------------
  $('talk').onclick = function () {
    if (!SR) {
      $('hint').textContent = 'This browser cannot listen. Chrome can; ' +
        'otherwise type below — she still answers out loud.';
      return;
    }
    listening = true;
    setTalk(true);
    $('hint').textContent = 'Listening — just talk, then pause.';
    start();
  };

  $('stop').onclick = function () {
    listening = false;
    setTalk(false);
    stopRecog();
    if (synth) synth.cancel();
    target = 0;
    say('Ready');
    $('hint').textContent = 'Stopped. Press Start to talk again.';
  };

  $('mute').onclick = function () {
    muted = !muted;
    $('mute').textContent = muted ? 'Unmute' : 'Mute';
    if (muted && synth) { synth.cancel(); target = 0; }
  };

  function sendTyped() {
    var v = $('typed').value.trim();
    if (!v || busy) return;
    $('typed').value = '';
    ask(v);
  }
  $('send').onclick = sendTyped;
  $('typed').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); sendTyped(); }
  });

  // Keep the conversation: it goes to the chat page, which reads the same key.
  $('save').onclick = function () {
    try {
      sessionStorage.setItem('mentora_voice_log', JSON.stringify(history));
      localStorage.setItem('mentora_chat_log', JSON.stringify(history));
      $('save').textContent = 'Saved';
      setTimeout(function () { $('save').textContent = 'Save to chat'; }, 1600);
    } catch (e) {}
  };

  // Settings decide the language and which teacher appears.
  fetch('/api/settings').then(function (r) { return r.json(); }).then(function (s) {
    if (s.avatar && svg) svg.setAttribute('data-variant', s.avatar);
    var map = {en: 'en-US', hi: 'hi-IN', ta: 'ta-IN', te: 'te-IN',
               kn: 'kn-IN', mr: 'mr-IN', bn: 'bn-IN', es: 'es-ES'};
    lang = map[s.language] || 'en-US';
    voice = null;
  }).catch(function () {});

  if (synth) synth.onvoiceschanged = function () { voice = pickVoice(); };

  // Restore anything said earlier this session.
  try {
    var saved = JSON.parse(sessionStorage.getItem('mentora_voice_log') || '[]');
    saved.forEach(function (t) { add(t.role, t.text); });
    history = saved;
  } catch (e) {}

  if (!SR) {
    $('hint').textContent = 'This browser cannot listen — Chrome can. ' +
      'You can still type, and she answers out loud.';
  }
})();
