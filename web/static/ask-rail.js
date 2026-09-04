/* Ask Mentora — the talk-to-AI control, on the left, on every page.
 *
 * It used to be a sticky footer bar that existed only on the dashboard, so
 * the one place a student is most likely to have a question — mid-lesson —
 * had no way to ask one. This renders it once, from one file, so the pages
 * do not each grow their own copy that drifts.
 *
 * Where it lands depends on the page: the dashboard already has a left
 * sidebar, so it goes inside it and scrolls with it. Every other page has a
 * centred column and no rail, so it becomes a fixed tab on the left edge
 * that expands when clicked. Both read as "the ask box is on the left"
 * without restructuring six different layouts.
 */
(function () {
  var ACID = '#e8ff00', INK = '#000';

  function go(value) {
    var q = (value || '').trim();
    if (q) window.location = '/discuss?q=' + encodeURIComponent(q);
  }

  function listen(input, button) {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      button.title = 'Speech recognition needs Chrome';
      button.style.opacity = '0.45';
      return;
    }
    var r = new SR();
    r.continuous = false;
    r.interimResults = false;
    r.lang = document.documentElement.lang || 'en-US';
    r.onresult = function (e) {
      input.value = e.results[0][0].transcript;
      input.focus();
    };
    r.onerror = function () { button.style.background = ''; };
    r.onend = function () { button.style.background = ACID; };
    button.style.background = INK;
    r.start();
  }

  function panel(compact) {
    var box = document.createElement('div');
    box.className = 'ask-mentora';
    box.style.cssText = 'border:3px solid ' + INK + ';background:#fff;padding:1rem;' +
      (compact ? 'box-shadow:8px 8px 0 0 #000;width:280px;' : 'box-shadow:5px 5px 0 0 #000;');
    box.innerHTML =
      '<div style="font-family:\'Space Mono\',monospace;font-size:10px;font-weight:700;' +
      'text-transform:uppercase;letter-spacing:0.12em;color:rgba(0,0,0,0.5);margin-bottom:0.6rem;">' +
      'Ask Mentora</div>' +
      '<textarea rows="2" placeholder="Ask a follow-up question..." ' +
      'style="width:100%;border:3px solid ' + INK + ';padding:0.6rem;font-family:inherit;' +
      'font-size:0.9rem;resize:vertical;outline:none;"></textarea>' +
      '<div style="display:flex;gap:0.5rem;margin-top:0.6rem;">' +
      '<button data-mic title="Push to talk" style="flex:none;width:44px;height:44px;' +
      'border:3px solid ' + INK + ';background:' + ACID + ';cursor:pointer;font-size:1.1rem;">&#127908;</button>' +
      '<button data-send style="flex:1;border:3px solid ' + INK + ';background:' + INK + ';' +
      'color:' + ACID + ';font-family:\'Archivo Black\',sans-serif;text-transform:uppercase;' +
      'font-size:0.75rem;letter-spacing:0.05em;cursor:pointer;padding:0.6rem;">Ask</button>' +
      '</div>';

    var input = box.querySelector('textarea');
    box.querySelector('[data-send]').onclick = function () { go(input.value); };
    box.querySelector('[data-mic]').onclick = function () { listen(input, this); };
    input.addEventListener('keydown', function (e) {
      // Enter sends; Shift+Enter is a newline, since a question can be long.
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go(input.value); }
    });
    return box;
  }

  function mount() {
    if (document.querySelector('.ask-mentora')) return;

    var sidebar = document.querySelector('aside');
    if (sidebar) {
      var slot = sidebar.querySelector('.p-6') || sidebar;
      slot.appendChild(panel(false));
      return;
    }

    // No sidebar: a tab pinned to the left edge, out of the way until asked
    // for. Fixed rather than in-flow so it cannot disturb a centred layout.
    var wrap = document.createElement('div');
    wrap.style.cssText = 'position:fixed;left:0;top:50%;transform:translateY(-50%);' +
      'z-index:60;display:flex;align-items:center;';

    var tab = document.createElement('button');
    tab.textContent = 'ASK';
    tab.style.cssText = 'writing-mode:vertical-rl;border:3px solid ' + INK + ';' +
      'background:' + ACID + ';font-family:\'Archivo Black\',sans-serif;font-size:0.75rem;' +
      'letter-spacing:0.15em;padding:1rem 0.35rem;cursor:pointer;box-shadow:5px 5px 0 0 #000;' +
      'border-left:none;';

    var body = panel(true);
    body.style.display = 'none';
    body.style.marginLeft = '0.5rem';

    tab.onclick = function () {
      var open = body.style.display === 'none';
      body.style.display = open ? 'block' : 'none';
      if (open) { var t = body.querySelector('textarea'); if (t) t.focus(); }
    };

    wrap.appendChild(tab);
    wrap.appendChild(body);
    document.body.appendChild(wrap);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
