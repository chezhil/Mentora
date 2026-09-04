/* The left rail: where you go, and how you ask. On every page, from one file.
 *
 * Quick Actions used to live in the dashboard's right column and nowhere
 * else, and the ask box was a sticky footer on that same page only -- so the
 * two places a student most often wants ("take me somewhere" and "answer my
 * question") existed on exactly one screen. Both are here now, rendered from
 * a single definition so the pages cannot drift apart.
 *
 * Where it lands depends on the page. The dashboard has a real left sidebar,
 * so the rail goes inside it and scrolls with it. Every other page is a
 * centred column with no rail, so it becomes a tab pinned to the left edge
 * that expands when clicked -- fixed, so it cannot disturb a layout it knows
 * nothing about.
 */
(function () {
  var ACID = '#e8ff00', INK = '#000';

  var LINKS = [
    {href: '/upload',    label: 'Start new lesson', primary: true},
    {href: '/upload',    label: 'View materials'},
    {href: '/review',    label: 'Review progress'},
    {href: '/dashboard', label: 'Dashboard'},
    {href: '/config',    label: 'Settings'}
  ];

  function here(href) {
    var path = window.location.pathname;
    return href === path || (href === '/review' && path === '/mentora-session-review');
  }

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
    r.onresult = function (e) { input.value = e.results[0][0].transcript; input.focus(); };
    r.onerror = function () { button.style.background = ACID; };
    r.onend = function () { button.style.background = ACID; };
    button.style.background = INK;
    r.start();
  }

  function heading(text) {
    return '<div style="font-family:\'Space Mono\',monospace;font-size:10px;' +
      'font-weight:700;text-transform:uppercase;letter-spacing:0.12em;' +
      'color:rgba(0,0,0,0.5);margin-bottom:0.6rem;">' + text + '</div>';
  }

  function nav() {
    var box = document.createElement('div');
    box.style.cssText = 'margin-bottom:1.25rem;';
    box.innerHTML = heading('Quick actions') + LINKS.map(function (l) {
      var on = here(l.href);
      return '<a href="' + l.href + '" style="display:block;border:3px solid ' + INK + ';' +
        'background:' + (l.primary ? ACID : (on ? '#f4f1ea' : '#fff')) + ';' +
        'color:' + INK + ';text-decoration:none;padding:0.6rem 0.75rem;margin-bottom:0.5rem;' +
        'font-family:\'Archivo Black\',sans-serif;text-transform:uppercase;font-size:0.72rem;' +
        'letter-spacing:0.04em;box-shadow:4px 4px 0 0 #000;">' + l.label + '</a>';
    }).join('');
    return box;
  }

  function ask() {
    var box = document.createElement('div');
    box.innerHTML = heading('Ask Mentora') +
      '<textarea rows="2" placeholder="Ask a follow-up question..." ' +
      'style="width:100%;border:3px solid ' + INK + ';padding:0.6rem;font-family:inherit;' +
      'font-size:0.9rem;resize:vertical;outline:none;"></textarea>' +
      '<div style="display:flex;gap:0.5rem;margin-top:0.6rem;">' +
      '<button data-mic title="Push to talk" style="flex:none;width:44px;height:44px;' +
      'border:3px solid ' + INK + ';background:' + ACID + ';cursor:pointer;font-size:1.1rem;">&#127908;</button>' +
      '<button data-send style="flex:1;border:3px solid ' + INK + ';background:' + INK + ';' +
      'color:' + ACID + ';font-family:\'Archivo Black\',sans-serif;text-transform:uppercase;' +
      'font-size:0.75rem;letter-spacing:0.05em;cursor:pointer;padding:0.6rem;">Ask</button></div>';

    var input = box.querySelector('textarea');
    box.querySelector('[data-send]').onclick = function () { go(input.value); };
    box.querySelector('[data-mic]').onclick = function () { listen(input, this); };
    input.addEventListener('keydown', function (e) {
      // Enter sends; Shift+Enter is a newline, since a question can be long.
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go(input.value); }
    });
    return box;
  }

  function rail(compact) {
    var box = document.createElement('div');
    box.className = 'mentora-rail';
    box.style.cssText = 'border:3px solid ' + INK + ';background:#fff;padding:1rem;' +
      (compact ? 'box-shadow:8px 8px 0 0 #000;width:270px;max-height:86vh;overflow:auto;'
               : 'box-shadow:5px 5px 0 0 #000;');
    box.appendChild(nav());
    box.appendChild(ask());
    return box;
  }

  function visible(el) {
    // offsetParent is null for anything display:none, which is what the
    // dashboard's `hidden lg:flex` sidebar is below 1024px. Testing for the
    // element's EXISTENCE would have mounted the rail inside a hidden
    // sidebar, so on a narrow window the navigation would simply be gone --
    // and it is the only navigation now.
    return !!el && el.offsetParent !== null;
  }

  function mount() {
    if (document.querySelector('.mentora-rail')) return;

    var sidebar = document.querySelector('aside');
    if (visible(sidebar)) {
      (sidebar.querySelector('.p-6') || sidebar).appendChild(rail(false));
      return;
    }

    var wrap = document.createElement('div');
    wrap.style.cssText = 'position:fixed;left:0;top:50%;transform:translateY(-50%);' +
      'z-index:60;display:flex;align-items:center;';

    var tab = document.createElement('button');
    tab.textContent = 'MENU';
    tab.style.cssText = 'writing-mode:vertical-rl;border:3px solid ' + INK + ';' +
      'background:' + ACID + ';font-family:\'Archivo Black\',sans-serif;font-size:0.75rem;' +
      'letter-spacing:0.15em;padding:1rem 0.35rem;cursor:pointer;box-shadow:5px 5px 0 0 #000;' +
      'border-left:none;';

    var body = rail(true);
    body.style.display = 'none';
    body.style.marginLeft = '0.5rem';

    tab.onclick = function () {
      var open = body.style.display === 'none';
      body.style.display = open ? 'block' : 'none';
      tab.textContent = open ? 'CLOSE' : 'MENU';
    };

    wrap.appendChild(tab);
    wrap.appendChild(body);
    document.body.appendChild(wrap);
  }

  function remount() {
    var existing = document.querySelector('.mentora-rail');
    if (!existing) return mount();
    var inSidebar = !!existing.closest('aside');
    var shouldBeInSidebar = visible(document.querySelector('aside'));
    if (inSidebar === shouldBeInSidebar) return;
    var host = existing.closest('div[style*="position:fixed"]') || existing;
    host.remove();
    mount();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }

  var t;
  window.addEventListener('resize', function () {
    clearTimeout(t);
    t = setTimeout(remount, 200);
  });
})();
