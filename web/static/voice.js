/* Voice mode: talk to the teacher, she talks back with diagrams, equations,
 * and step-by-step breakdowns.
 *
 * Speech in and speech out both happen HERE, in the browser. The server
 * pipeline that renders a lesson takes 30-60 seconds per turn -- fine for a
 * lesson you sit and watch, useless for a conversation. SpeechRecognition and
 * speechSynthesis answer in the time it takes to think, which is what makes
 * this feel live.
 *
 * Enhancements over the base version:
 * - Audio visualizer bars that pulse during speech
 * - Live Mermaid diagram rendering in the board
 * - KaTeX equation rendering inline
 * - Step-by-step breakdown extraction from teacher answers
 * - Diagram gallery sidebar
 * - Quick prompt suggestions
 * - Session stats tracking
 */
(function () {
  var $ = function (id) { return document.getElementById(id); };

  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var synth = window.speechSynthesis;

  var history = [];          // {role, text}
  var listening = false;
  var busy = false;
  var muted = false;
  var recog = null;
  var lang = 'en-US';
  var voice = null;

  // Session stats
  var stats = { questions: 0, diagrams: 0, equations: 0, startTime: Date.now() };

  // Mermaid config
  var mermaidReady = false;
  try {
    mermaid.initialize({
      startOnLoad: false,
      theme: 'base',
      themeVariables: {
        primaryColor: '#e8ff00',
        primaryBorderColor: '#000',
        primaryTextColor: '#000',
        lineColor: '#000',
        secondaryColor: '#f4f1ea',
        tertiaryColor: '#fff',
        fontFamily: 'Archivo, sans-serif'
      },
      securityLevel: 'loose'
    });
    mermaidReady = true;
  } catch (e) { mermaidReady = false; }

  // ---- Audio visualizer ---------------------------------------------------
  var visBars = [];
  var visContainer = $('audioVis');
  if (visContainer) {
    for (var i = 0; i < 32; i++) {
      var bar = document.createElement('div');
      bar.className = 'bar';
      bar.style.height = '3px';
      visContainer.appendChild(bar);
      visBars.push(bar);
    }
  }

  var visActive = false;
  var visInterval = null;

  function startVis() {
    visActive = true;
    visContainer.classList.remove('idle');
    clearInterval(visInterval);
    visInterval = setInterval(function () {
      visBars.forEach(function (b) {
        var h = 3 + Math.random() * 38;
        b.style.height = h + 'px';
      });
    }, 80);
  }

  function pulseVis() {
    visBars.forEach(function (b) {
      b.style.height = (8 + Math.random() * 30) + 'px';
    });
  }

  function stopVis() {
    visActive = false;
    clearInterval(visInterval);
    visContainer.classList.add('idle');
    visBars.forEach(function (b) { b.style.height = '3px'; });
  }

  // ---- Avatar -------------------------------------------------------------
  var avatar3D = window.Avatar3D ? new window.Avatar3D($('avatar')) : null;
  var svg = $('avatar_svg_disabled');
  var mouthCavity = svg && svg.querySelector('#mouthCavity');
  var mouthLine = svg && svg.querySelector('#mouthLine');
  var head = svg && svg.querySelector('#head');
  var eyeL = svg && svg.querySelector('#eyeL');
  var eyeR = svg && svg.querySelector('#eyeR');

  var openness = 0, target = 0, t0 = performance.now();

  function frame(now) {
    var t = (now - t0) / 1000;
    openness += (target - openness) * 0.35;

    if (mouthCavity) {
      var ry = 2 + openness * 13;
      mouthCavity.setAttribute('ry', ry.toFixed(2));
      mouthCavity.setAttribute('rx', (24 - openness * 6).toFixed(2));
    }
    if (mouthLine) mouthLine.style.opacity = Math.max(0, 1 - openness * 2.2);

    var life = 0.4 + openness * 1.2;
    var sway = Math.sin(t * 0.7) * 2.4 * life;
    var nod = Math.sin(t * 1.3) * 1.4 * life;
    if (head) head.setAttribute('transform',
      'translate(' + sway.toFixed(2) + ',' + nod.toFixed(2) + ')');

    if (avatar3D) {
      avatar3D.setMouthOpen(openness);
      avatar3D.setHeadTransform(sway, nod);
    }

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

  // ---- Transcript ---------------------------------------------------------
  function add(role, text) {
    var empty = $('empty');
    if (empty) empty.remove();
    var el = document.createElement('div');
    el.className = 'turn ' + role;
    var now = new Date();
    var ts = now.getHours().toString().padStart(2, '0') + ':' +
             now.getMinutes().toString().padStart(2, '0');
    el.innerHTML = '<div class="label">' + (role === 'student' ? 'You' : 'Mentora') +
      '</div><p></p><div class="timestamp">' + ts + '</div>';
    el.querySelector('p').textContent = text;
    $('log').appendChild(el);
    $('log').scrollTop = $('log').scrollHeight;
    history.push({role: role, text: text});
    $('turnCount').textContent = history.length + ' turns';
    try {
      sessionStorage.setItem('mentora_voice_log', JSON.stringify(history));
    } catch (e) {}
    return el;
  }

  // ---- Content parsing: extract diagrams, equations, steps ----------------

  function extractMermaidBlocks(text) {
    var blocks = [];
    var re = /```mermaid\s*\n([\s\S]*?)```/gi;
    var m;
    while ((m = re.exec(text)) !== null) {
      blocks.push(m[1].trim());
    }
    return blocks;
  }

  function extractEquations(text) {
    var eqs = [];
    // LaTeX inline: $...$ or \(...\)
    var reInline = /\$([^$\n]+)\$/g;
    var reBlock = /\$\$([\s\S]+?)\$\$/g;
    var reParen = /\\\((.+?)\\\)/g;
    var m;
    while ((m = reBlock.exec(text)) !== null) eqs.push({ tex: m[1].trim(), display: true });
    while ((m = reInline.exec(text)) !== null) eqs.push({ tex: m[1].trim(), display: false });
    while ((m = reParen.exec(text)) !== null) eqs.push({ tex: m[1].trim(), display: false });
    return eqs;
  }

  function extractSteps(text) {
    var steps = [];
    // Numbered lists: 1. ...  2. ... etc.
    var reNum = /(?:^|\n)\s*(?:\d+[\.\)]\s+)(.+)/g;
    var m;
    while ((m = reNum.exec(text)) !== null) {
      steps.push(m[1].trim());
    }
    if (steps.length >= 2) return steps;
    // Bullet lists
    steps = [];
    var reBullet = /(?:^|\n)\s*[-*•]\s+(.+)/g;
    while ((m = reBullet.exec(text)) !== null) {
      steps.push(m[1].trim());
    }
    return steps.length >= 2 ? steps : [];
  }

  function extractKeyConcepts(text) {
    var concepts = [];
    // Look for **bold** phrases
    var reBold = /\*\*([^*]+)\*\*/g;
    var m;
    while ((m = reBold.exec(text)) !== null) {
      concepts.push(m[1].trim());
    }
    // De-duplicate
    return [...new Set(concepts)].slice(0, 8);
  }

  function cleanAnswer(text) {
    // Remove mermaid blocks from displayed text
    return text.replace(/```mermaid\s*\n[\s\S]*?```/gi, '[Diagram rendered below]')
               .replace(/\$\$[\s\S]+?\$\$/g, '[Equation rendered below]')
               .trim();
  }

  // ---- Board rendering: Mermaid + KaTeX + images --------------------------

  var diagramHistory = [];

  async function renderMermaid(container, code) {
    if (!mermaidReady) {
      container.innerHTML = '<pre style="padding:1rem;background:var(--paper);border:3px solid var(--ink);font-size:0.8rem;overflow-x:auto;">' +
        escapeHtml(code) + '</pre>';
      return;
    }
    try {
      var id = 'mermaid-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
      var { svg: svgCode } = await mermaid.render(id, code);
      var wrapper = document.createElement('div');
      wrapper.innerHTML = svgCode;
      wrapper.style.textAlign = 'center';
      wrapper.style.padding = '0.5rem';
      container.appendChild(wrapper);

      // Add to gallery
      addToGallery(code, 'Diagram');
      stats.diagrams++;
      updateStats();
    } catch (e) {
      container.innerHTML = '<pre style="padding:1rem;background:#fff3f3;border:3px solid var(--ink);font-size:0.8rem;">Diagram error: ' +
        escapeHtml(e.message || 'Could not render') + '\n\n' + escapeHtml(code) + '</pre>';
    }
  }

  function renderKaTeX(container, tex, display) {
    if (typeof katex === 'undefined') {
      container.innerHTML += '<code>' + escapeHtml(tex) + '</code>';
      return;
    }
    try {
      var span = document.createElement(display ? 'div' : 'span');
      katex.render(tex, span, { displayMode: display, throwOnError: false });
      if (display) {
        span.style.margin = '0.5rem 0';
        span.style.textAlign = 'center';
        span.style.padding = '0.5rem';
        span.style.border = '2px solid var(--ink)';
        span.style.background = 'var(--paper)';
      }
      container.appendChild(span);
      stats.equations++;
      updateStats();
    } catch (e) {
      container.innerHTML += '<code>' + escapeHtml(tex) + '</code>';
    }
  }

  function renderBoard(data) {
    var board = $('board');
    var content = $('boardContent');
    if (!board || !content) return;

    content.innerHTML = '';
    board.style.display = 'block';

    var caption = data.caption || 'On the board';
    $('boardCap').textContent = caption;

    // 1. If server returned an image, show it
    if (data.image) {
      var imgWrap = document.createElement('div');
      imgWrap.innerHTML = '<img alt="' + escapeHtml(caption) + '" src="' + data.image + '" style="width:100%;border:3px solid var(--ink);">';
      content.appendChild(imgWrap);
      addToGallery(null, caption, data.image);
    }

    // 2. Extract and render Mermaid blocks from answer
    var mermaidBlocks = extractMermaidBlocks(data.answer || '');
    mermaidBlocks.forEach(function (code) {
      var div = document.createElement('div');
      div.style.marginTop = '0.75rem';
      content.appendChild(div);
      renderMermaid(div, code);
    });

    // 3. Render inline equations
    var eqs = extractEquations(data.answer || '');
    if (eqs.length > 0) {
      var eqContainer = document.createElement('div');
      eqContainer.style.marginTop = '0.75rem';
      eqContainer.style.padding = '0.75rem';
      eqContainer.style.border = '3px solid var(--ink)';
      eqContainer.style.background = 'var(--paper)';
      eqContainer.innerHTML = '<div class="label">Equations</div>';
      eqs.forEach(function (eq) { renderKaTeX(eqContainer, eq.tex, eq.display); });
      content.appendChild(eqContainer);
    }

    // 4. Extract and show steps
    var steps = extractSteps(data.answer || '');
    if (steps.length >= 2) {
      var stepsPanel = $('stepsPanel');
      var stepsList = $('stepsList');
      if (stepsPanel && stepsList) {
        stepsPanel.style.display = 'block';
        stepsList.innerHTML = '';
        steps.forEach(function (s, i) {
          var div = document.createElement('div');
          div.className = 'step';
          div.innerHTML = '<div class="step-num">' + (i + 1) + '</div><div class="step-text">' + escapeHtml(s) + '</div>';
          stepsList.appendChild(div);
        });
      }
    }

    // 5. Extract key concepts
    var concepts = extractKeyConcepts(data.answer || '');
    if (concepts.length > 0) {
      var panel = $('conceptsPanel');
      var list = $('conceptsList');
      if (panel && list) {
        panel.style.display = 'block';
        list.innerHTML = '';
        concepts.forEach(function (c) {
          var div = document.createElement('div');
          div.style.cssText = 'padding:0.35rem 0.5rem;margin-bottom:0.3rem;background:var(--acid);border:2px solid var(--ink);font-size:0.78rem;font-weight:700;';
          div.textContent = c;
          list.appendChild(div);
        });
      }
    }
  }

  function addToGallery(code, caption, imageUrl) {
    var panel = $('galleryPanel');
    var gallery = $('gallery');
    if (!panel || !gallery) return;
    panel.style.display = 'block';

    var item = document.createElement('div');
    item.className = 'gallery-item';

    if (imageUrl) {
      item.innerHTML = '<img src="' + imageUrl + '" alt="' + escapeHtml(caption) + '">';
    } else if (code && mermaidReady) {
      var renderDiv = document.createElement('div');
      renderDiv.style.padding = '0.5rem';
      renderDiv.style.background = '#fff';
      item.appendChild(renderDiv);
      var id = 'gal-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
      mermaid.render(id, code).then(function (r) {
        renderDiv.innerHTML = r.svg;
      }).catch(function () {
        renderDiv.innerHTML = '<pre style="font-size:0.65rem;">' + escapeHtml(code) + '</pre>';
      });
    }

    var cap = document.createElement('div');
    cap.className = 'gallery-cap';
    cap.textContent = caption || 'Visual';
    item.appendChild(cap);

    gallery.insertBefore(item, gallery.firstChild);
    diagramHistory.push({ code: code, caption: caption, image: imageUrl });
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function updateStats() {
    $('statQuestions').textContent = stats.questions;
    $('statDiagrams').textContent = stats.diagrams;
    $('statEquations').textContent = stats.equations;
    var mins = Math.round((Date.now() - stats.startTime) / 60000);
    $('statTime').textContent = mins + 'm';
  }
  setInterval(updateStats, 30000);

  // ---- Speaking -----------------------------------------------------------
  function pickVoice() {
    var all = synth.getVoices();
    if (!all.length) return null;
    var base = lang.split('-')[0];
    var exact = all.filter(function (v) { return v.lang === lang; });
    var loose = all.filter(function (v) { return v.lang.indexOf(base) === 0; });
    var pool = exact.length ? exact : (loose.length ? loose : all);
    var nice = pool.filter(function (v) { return /natural|neural|premium|enhanced/i.test(v.name); });
    return (nice[0] || pool[0]);
  }

  function speak(text, done) {
    // The callback MUST fire exactly once, and it must fire. Readiness is
    // gated on it -- busy is only cleared here -- and speechSynthesis does
    // not always deliver onend: a backgrounded tab, a voice the platform
    // will not load, or speech blocked before a user gesture all leave the
    // utterance hanging. When that happened the page bricked itself in
    // silence: every later click was swallowed by `busy`, with no error and
    // nothing on screen to explain it. A watchdog releases it.
    var finished = false;
    var guard = null;
    function settle() {
      if (finished) return;
      finished = true;
      if (guard) { clearTimeout(guard); guard = null; }
      target = 0;
      done();
    }

    if (muted || !synth) { settle(); return; }

    var u;
    try {
      synth.cancel();
      u = new SpeechSynthesisUtterance(text);
    } catch (e) {
      settle();
      return;
    }
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
    u.onend = settle;
    u.onerror = settle;

    // Generous but finite: roughly real speaking time plus slack, so a
    // hung utterance costs a pause rather than the rest of the session.
    var words = String(text || '').split(/\s+/).length;
    guard = setTimeout(settle, Math.max(6000, words * 600 + 4000));

    try {
      synth.speak(u);
    } catch (e) {
      settle();
    }
  }

  // ---- The exchange -------------------------------------------------------
  var inflight = null, ticker = null, startedAt = 0;

  function workOn(label) {
    startedAt = performance.now();
    $('work').style.display = 'block';
    $('workLabel').textContent = label;
    $('elapsed').textContent = '0.0s';
    $('workBar').style.width = '10%';
    $('cancel').disabled = false;
    $('cancel').textContent = 'Cancel';
    clearInterval(ticker);
    ticker = setInterval(function () {
      var secs = (performance.now() - startedAt) / 1000;
      $('elapsed').textContent = secs.toFixed(1) + 's';
      // Animate progress bar
      var pct = Math.min(90, 10 + secs * 3);
      $('workBar').style.width = pct + '%';
    }, 100);
    gate(true);
  }

  function workOff() {
    clearInterval(ticker);
    ticker = null;
    $('work').style.display = 'none';
    $('workBar').style.width = '100%';
    setTimeout(function () { $('workBar').style.width = '0%'; }, 400);
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
    if (busy) return;
    busy = true;
    stats.questions++;
    updateStats();
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

    // Render the board with diagrams, equations, steps
    renderBoard(d);

    var displayText = cleanAnswer(d.answer);
    add('teacher', displayText);
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

  // ---- Listening ----------------------------------------------------------
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

  // ---- Wiring -------------------------------------------------------------
  $('cancel').onclick = function () {
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
    stopVis();
    say('Ready');
    $('hint').textContent = 'Stopped. Press Start to talk again.';
  };

  $('mute').onclick = function () {
    muted = !muted;
    $('mute').textContent = muted ? 'Unmute' : 'Mute';
    if (muted && synth) { synth.cancel(); target = 0; stopVis(); }
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

  // Quick prompts
  document.querySelectorAll('.quick-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (busy) return;
      var q = btn.getAttribute('data-q');
      if (q) { $('typed').value = q; sendTyped(); }
    });
  });

  // Board fullscreen
  $('boardFullscreen').addEventListener('click', function () {
    var modal = $('boardModal');
    var content = $('boardContent');
    var cap = $('boardCap');
    if (modal && content) {
      $('modalCap').textContent = cap.textContent;
      $('modalContent').innerHTML = content.innerHTML;
      modal.style.display = 'block';
    }
  });

  // Save
  $('save').onclick = function () {
    try {
      sessionStorage.setItem('mentora_voice_log', JSON.stringify(history));
      localStorage.setItem('mentora_chat_log', JSON.stringify(history));
      $('save').textContent = 'Saved';
      setTimeout(function () { $('save').textContent = 'Save to chat'; }, 1600);
    } catch (e) {}
  };

  // ---- Pickers ------------------------------------------------------------
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

  // Restore earlier session
  try {
    var saved = JSON.parse(sessionStorage.getItem('mentora_voice_log') || '[]');
    saved.forEach(function (t) { add(t.role, t.text); });
    history = saved;
  } catch (e) {}

  if (!SR) {
    $('hint').textContent = 'This browser cannot listen — Chrome can. ' +
      'You can still type, and she answers out loud.';
  }

  // Init stats
  updateStats();
})();
