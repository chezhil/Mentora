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
  // One request in flight, one cancel for it. Every send path checks `busy`
  // and every control that could start or stop a turn is disabled while it
  // runs, so a second click cannot queue a second question, and Cancel cannot
  // be pressed twice into an already-aborted request.
  var inflight = null, ticker = null, startedAt = 0;

  function workOn(label) {
    startedAt = performance.now();
    $('work').style.display = 'block';
    $('workLabel').textContent = label;
    $('elapsed').textContent = '0.0s';
    $('cancel').disabled = false;
    $('cancel').textContent = 'Cancel';
    clearInterval(ticker);
    ticker = setInterval(function () {
      $('elapsed').textContent = ((performance.now() - startedAt) / 1000).toFixed(1) + 's';
    }, 100);
    gate(true);
  }

  function workOff() {
    clearInterval(ticker);
    ticker = null;
    $('work').style.display = 'none';
    inflight = null;
    gate(false);
  }

  function gate(on) {
    ['talk', 'send', 'preview', 'teacher', 'lang', 'voice'].forEach(function (id) {
      var el = $(id);
      if (el) el.disabled = on;
    });
    $('typed').disabled = on;
  }

  async function ask(text) {
    if (busy) return;                    // second click while thinking: ignored
    busy = true;
    add('student', text);
    say('Thinking');
    workOn('Thinking');

    var d;
    try {
      inflight = new AbortController();
      var r = await fetch('/api/voice/reply', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: text, history: history.slice(0, -1),
                              language: langCode()}),
        signal: inflight.signal,
      });
      d = await r.json();
      if (!r.ok) throw new Error(d.error || 'The teacher could not answer.');
    } catch (e) {
      busy = false;
      workOff();
      say('Ready');
      if (e.name !== 'AbortError') {
        add('teacher', 'Sorry — ' + e.message);
        $('hint').textContent = 'Something went wrong. Try again.';
      } else {
        $('hint').textContent = 'Cancelled.';
      }
      if (listening && e.name !== 'AbortError') start();
      return;
    }
    workOff();

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
  $('cancel').onclick = function () {
    // Disabled immediately: an abort cannot be issued twice, and the button
    // should not look live once it has done its job.
    $('cancel').disabled = true;
    $('cancel').textContent = 'Cancelling…';
    if (inflight) { try { inflight.abort(); } catch (e) {} }
  };

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
  function langCode() { return ($('lang') && $('lang').value) || lang; }
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

  // ---- pickers ------------------------------------------------------------
  var LOCALE = {en: 'en-US', hi: 'hi-IN', ta: 'ta-IN', te: 'te-IN',
                kn: 'kn-IN', mr: 'mr-IN', bn: 'bn-IN', es: 'es-ES'};

  function remember(key, value) {
    try { localStorage.setItem('mentora_voice_' + key, value); } catch (e) {}
  }
  function recall(key) {
    try { return localStorage.getItem('mentora_voice_' + key); } catch (e) { return null; }
  }

  function fillTeachers(selected) {
    var list = window.MENTORA_TEACHERS || [];
    $('teacher').innerHTML = list.map(function (t) {
      return '<option value="' + t.id + '">' + t.name + ' — ' + t.note + '</option>';
    }).join('');
    $('teacher').value = selected || list[0].id;
    applyTeacher();
  }

  function applyTeacher() {
    var t = window.teacherById($('teacher').value);
    window.paintTeacher(svg, t);
    remember('teacher', t.id);
    // Persist it: the same teacher should appear in the rendered lessons, not
    // only here. avatar keeps the rig (f/m); teacher carries the palette.
    fetch('/api/settings', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({teacher: t.id, avatar: t.variant}),
    }).catch(function () {});
  }

  function fillLanguages(list, selected) {
    $('lang').innerHTML = list.map(function (l) {
      return '<option value="' + l.code + '">' + l.name + '</option>';
    }).join('');
    $('lang').value = selected || 'en';
  }

  // Which voices the platform actually has for this language. The list is
  // asynchronous in Chrome, so this runs again on voiceschanged.
  function fillVoices() {
    if (!synth) return;
    var code = ($('lang').value || 'en');
    lang = LOCALE[code] || 'en-US';
    var base = lang.split('-')[0];
    var all = synth.getVoices();
    var pool = all.filter(function (v) { return v.lang.replace('_', '-').indexOf(base) === 0; });

    if (!pool.length) {
      $('voice').innerHTML = '<option value="">No ' + code +
        ' voice installed — she will use the default</option>';
      voice = null;
      $('preview').disabled = true;
      return;
    }
    $('preview').disabled = false;
    // macOS ships a pile of novelty voices -- Bad News, Bahh, Bells, Zarvox --
    // and they sort to the top alphabetically, so the first thing offered as
    // a teacher was a joke. Rank by how much it sounds like a person.
    var NOVELTY = /^(albert|bad news|bahh|bells|boing|bubbles|cellos|good news|jester|organ|superstar|trinoids|whisper|wobble|zarvox|junior|kathy|princess|deranged|hysterical|bruce|fred|ralph|agnes|grandma|grandpa|rocko|shelley|sandy|flo|eddy|reed|rishi)/i;
    var GOOD = /natural|neural|premium|enhanced|google|microsoft|siri/i;
    pool.sort(function (a, b) {
      var rank = function (v) {
        if (NOVELTY.test(v.name)) return 3;
        if (GOOD.test(v.name)) return 0;
        return v.default ? 0 : 1;
      };
      return rank(a) - rank(b) || a.name.localeCompare(b.name);
    });
    $('voice').innerHTML = pool.map(function (v) {
      return '<option value="' + v.name + '">' + v.name + ' (' + v.lang + ')</option>';
    }).join('');
    var want = recall('voice');
    if (want && pool.some(function (v) { return v.name === want; })) $('voice').value = want;
    voice = pool.filter(function (v) { return v.name === $('voice').value; })[0] || pool[0];
  }

  $('teacher').addEventListener('change', applyTeacher);
  $('lang').addEventListener('change', function () {
    remember('lang', $('lang').value);
    voice = null;
    fillVoices();
  });
  $('voice').addEventListener('change', function () {
    var all = synth ? synth.getVoices() : [];
    voice = all.filter(function (v) { return v.name === $('voice').value; })[0] || null;
    remember('voice', $('voice').value);
  });
  $('preview').addEventListener('click', function () {
    var sample = {en: 'This is how I will sound.', hi: 'मैं ऐसे बोलूँगी।',
                  ta: 'நான் இப்படி பேசுவேன்.', te: 'నేను ఇలా మాట్లాడతాను.',
                  kn: 'ನಾನು ಹೀಗೆ ಮಾತನಾಡುತ್ತೇನೆ.', mr: 'मी अशी बोलेन.',
                  bn: 'আমি এভাবে কথা বলব।', es: 'Así es como sonaré.'};
    speak(sample[$('lang').value] || sample.en, function () {});
  });

  Promise.all([fetch('/api/settings').then(function (r) { return r.json(); }),
               window.teachersReady]).then(function (both) {
    var s = both[0];
    fillLanguages(s.languages || [{code: 'en', name: 'English'}],
                  recall('lang') || s.language || 'en');
    // A saved teacher wins over the Settings avatar: it is the more specific
    // choice, and it was made on this screen.
    var saved = recall('teacher');
    if (!saved) {
      var byVariant = (window.MENTORA_TEACHERS || []).filter(function (t) {
        return t.variant === (s.avatar || 'f');
      })[0];
      saved = byVariant ? byVariant.id : null;
    }
    fillTeachers(saved);
    fillVoices();
  }).catch(function () {
    fillLanguages([{code: 'en', name: 'English'}], 'en');
    fillTeachers(recall('teacher'));
    fillVoices();
  });

  if (synth) synth.onvoiceschanged = fillVoices;

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
