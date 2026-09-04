"""GSAP-inspired animations for Mentora.

Injects lightweight CSS animations and JS observers that mimic the best
GSAP showcase patterns — scroll reveals, staggered entrances, animated
counters, card hover effects, hero text animation — without requiring
the GSAP library.

Uses st.html() (Streamlit 1.62+) which renders HTML directly in the
main page DOM, not in an isolated iframe.
"""

import streamlit as st

_INJECTED_KEY = "__mentora_anim_injected"

_ANIM_JS = """
<script>
(function() {
  if (window.__mentoraAnimReady) return;
  window.__mentoraAnimReady = true;

  // 1. Scroll-reveal: elements with [data-reveal] fade up on scroll
  var revealObserver = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('revealed');
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

  function initReveals() {
    document.querySelectorAll('[data-reveal]:not(.revealed)').forEach(function(el) {
      revealObserver.observe(el);
    });
  }

  // 2. Animated counters: elements with [data-count-to] count up
  var counterObserver = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
      if (entry.isIntersecting) {
        animateCounter(entry.target);
        counterObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.3 });

  function animateCounter(el) {
    var target = parseFloat(el.getAttribute('data-count-to'));
    var suffix = el.getAttribute('data-count-suffix') || '';
    var prefix = el.getAttribute('data-count-prefix') || '';
    var duration = 1200;
    var start = performance.now();
    function tick(now) {
      var progress = Math.min((now - start) / duration, 1);
      var eased = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
      var current = Math.round(eased * target);
      el.textContent = prefix + current + suffix;
      if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  function initCounters() {
    document.querySelectorAll('[data-count-to]:not(.counted)').forEach(function(el) {
      el.classList.add('counted');
      counterObserver.observe(el);
    });
  }

  // 3. Stagger children: parent with [data-stagger] animates kids
  function initStagger() {
    document.querySelectorAll('[data-stagger]:not(.stagger-ready)').forEach(function(parent) {
      parent.classList.add('stagger-ready');
      var children = parent.children;
      for (var i = 0; i < children.length; i++) {
        children[i].style.animationDelay = (i * 0.1) + 's';
        children[i].classList.add('stagger-child');
      }
    });
  }

  // 4. Tilt hover: elements with [data-tilt] tilt on mousemove
  function initTilt() {
    document.querySelectorAll('[data-tilt]:not(.tilt-ready)').forEach(function(el) {
      el.classList.add('tilt-ready');
      el.addEventListener('mousemove', function(e) {
        var rect = el.getBoundingClientRect();
        var x = (e.clientX - rect.left) / rect.width - 0.5;
        var y = (e.clientY - rect.top) / rect.height - 0.5;
        el.style.transform = 'perspective(600px) rotateY(' + (x * 8) + 'deg) rotateX(' + (-y * 8) + 'deg) scale(1.02)';
      });
      el.addEventListener('mouseleave', function() {
        el.style.transform = '';
      });
    });
  }

  // 5. Magnetic buttons: elements with [data-magnetic] follow cursor
  function initMagnetic() {
    document.querySelectorAll('[data-magnetic]:not(.mag-ready)').forEach(function(el) {
      el.classList.add('mag-ready');
      el.addEventListener('mousemove', function(e) {
        var rect = el.getBoundingClientRect();
        var x = e.clientX - rect.left - rect.width / 2;
        var y = e.clientY - rect.top - rect.height / 2;
        el.style.transform = 'translate(' + (x * 0.3) + 'px, ' + (y * 0.3) + 'px)';
      });
      el.addEventListener('mouseleave', function() {
        el.style.transform = 'translate(0, 0)';
      });
    });
  }

  function initAll() {
    initReveals();
    initCounters();
    initStagger();
    initTilt();
    initMagnetic();
  }

  // Run after delay to let Streamlit render
  setTimeout(initAll, 500);
  setTimeout(initAll, 1500);

  // Re-init on DOM changes (Streamlit rerenders)
  var rerunObserver = new MutationObserver(function() {
    setTimeout(initAll, 400);
  });
  rerunObserver.observe(document.body, { childList: true, subtree: true });
})();
</script>
"""


def inject_animations() -> None:
    """Inject GSAP-inspired animation JS once per page.

    Uses st.html() which renders HTML directly in the main page DOM.
    """
    if st.session_state.get(_INJECTED_KEY):
        return
    st.session_state[_INJECTED_KEY] = True
    st.html(_ANIM_JS, unsafe_allow_javascript=True)
