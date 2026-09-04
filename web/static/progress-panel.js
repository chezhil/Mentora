/* The sidebar's progress panels, from one definition.
 *
 * The dashboard and the session review each shipped their own copy of the
 * same sidebar, so cleaning one left the other showing a difficulty select
 * that did nothing, persona buttons writing to a localStorage key nothing
 * reads, and a "Mentora Pro active" badge for a tier that does not exist.
 * Both pages now render this instead, and there is nothing left to drift.
 *
 * Every number here already existed in /api/dashboard and was being computed
 * and dropped: level and XP, streak, average score, the flashcard deck, and
 * the concepts the reports flagged as weak.
 */
(function () {
  function card(inner, extra) {
    return '<div class="border-[3px] border-black bg-white p-3 shadow-[5px_5px_0_0_#000000] ' +
      (extra || '') + '">' + inner + '</div>';
  }

  function label(text, cls) {
    return '<div class="font-mono text-[9px] font-bold uppercase tracking-widest ' +
      (cls || 'text-black/50') + '">' + text + '</div>';
  }

  function markup() {
    return '' +
      '<div>' +
        '<span class="font-mono text-xs font-bold uppercase tracking-widest text-black/65 mb-4 block">01 / Progress</span>' +

        '<div class="border-[3px] border-black bg-white p-4 shadow-[5px_5px_0_0_#000000] mb-4">' +
          '<div class="flex items-baseline justify-between mb-1">' +
            label('Level') +
            '<span class="font-black text-lg" data-p="level">1</span>' +
          '</div>' +
          '<div style="height:12px;border:3px solid #000;background:#fff;overflow:hidden;">' +
            '<div data-p="xpbar" style="height:100%;background:#e8ff00;width:0;transition:width .4s;"></div>' +
          '</div>' +
          '<div class="mt-1">' + label('<span data-p="xp">0 XP</span>', 'text-black/40') + '</div>' +
        '</div>' +

        '<div class="grid grid-cols-2 gap-3 mb-4">' +
          card('<div class="font-black text-2xl leading-none" data-p="streak">0</div>' +
               '<div class="mt-1">' + label('Day streak') + '</div>') +
          card('<div class="font-black text-2xl leading-none" data-p="avg">0%</div>' +
               '<div class="mt-1">' + label('Avg score') + '</div>') +
        '</div>' +

        '<a href="/flashcards" class="block border-[3px] border-black bg-[#e8ff00] p-3 ' +
        'shadow-[5px_5px_0_0_#000000] mb-4" style="text-decoration:none;color:#000;">' +
          '<div class="font-black text-sm uppercase leading-none" data-p="cards">0 flashcards</div>' +
          '<div class="mt-1">' + label('<span data-p="due">Nothing due</span>', 'text-black/60') + '</div>' +
        '</a>' +
      '</div>' +

      '<div>' +
        '<span class="font-mono text-xs font-bold uppercase tracking-widest text-black/65 mb-4 block">02 / Needs work</span>' +
        '<div data-p="weak"></div>' +
      '</div>';
  }

  async function fill(root) {
    var d;
    try {
      var r = await fetch('/api/dashboard');
      if (!r.ok) return;
      d = await r.json();
    } catch (e) { return; }

    var set = function (key, value) {
      var el = root.querySelector('[data-p="' + key + '"]');
      if (el) el.textContent = value;
    };

    set('level', d.level || 1);
    set('streak', d.streak || 0);
    set('avg', (d.avg_score || 0) + '%');
    set('cards', (d.total_cards || 0) + ' flashcard' + (d.total_cards === 1 ? '' : 's'));
    set('due', d.due_cards ? (d.due_cards + ' due for review') : 'Nothing due');

    var into = d.xp_into || 0;
    set('xp', (d.xp || 0) + ' XP · ' + Math.max(0, 200 - into) + ' to next');
    var bar = root.querySelector('[data-p="xpbar"]');
    if (bar) bar.style.width = Math.min(100, Math.round((into / 200) * 100)) + '%';

    var weak = root.querySelector('[data-p="weak"]');
    if (weak) {
      weak.innerHTML = (d.weak && d.weak.length)
        ? d.weak.slice(0, 4).map(function (w) {
            return '<div class="border-[3px] border-black bg-white p-3 ' +
              'shadow-[5px_5px_0_0_#000000] mb-3"><p class="text-xs font-medium ' +
              'leading-snug">' + w + '</p></div>';
          }).join('')
        : '<div class="border-[3px] border-black bg-white p-3 shadow-[5px_5px_0_0_#000000]">' +
          '<p class="font-mono text-[10px] uppercase tracking-widest text-black/40">' +
          'Nothing flagged yet — finish a lesson.</p></div>';
    }
  }

  function mount() {
    var slot = document.querySelector('aside .p-6');
    if (!slot || slot.querySelector('[data-p="level"]')) return;
    var box = document.createElement('div');
    box.className = 'mentora-progress';
    box.innerHTML = markup();
    // Ahead of the rail, which appends itself: progress first, then actions.
    slot.insertBefore(box, slot.firstChild);
    fill(box);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
