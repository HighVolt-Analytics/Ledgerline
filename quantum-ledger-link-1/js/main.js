(function () {
  'use strict';

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var hdr = document.getElementById('hdr');
  var burger = document.getElementById('burger');
  var mobnav = document.getElementById('mobnav');

  /* ---------- sticky header state (translucent + theme aware) ---------- */
  var paperIds = ['problem', 'how', 'mobile', 'team', 'pricing'];
  var paperSections = paperIds.map(function (id) { return document.getElementById(id); });

  function onScroll() {
    var y = window.scrollY || window.pageYOffset;
    hdr.classList.toggle('scrolled', y > 12);
    var probe = 32; // just under the header edge
    var onPaper = paperSections.some(function (el) {
      if (!el) return false;
      var r = el.getBoundingClientRect();
      return r.top <= probe && r.bottom > probe;
    });
    hdr.classList.toggle('on-paper', onPaper && y > 12);
  }
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll);

  /* ---------- mobile nav ---------- */
  function closeNav() {
    mobnav.classList.remove('open');
    burger.setAttribute('aria-expanded', 'false');
    burger.setAttribute('aria-label', 'Open menu');
  }
  burger.addEventListener('click', function () {
    var open = mobnav.classList.toggle('open');
    burger.setAttribute('aria-expanded', open ? 'true' : 'false');
    burger.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  });
  mobnav.addEventListener('click', function (e) {
    if (e.target.tagName === 'A') closeNav();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeNav();
  });

  /* ---------- smooth scroll with header offset ---------- */
  document.querySelectorAll('a[href^="#"]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var id = a.getAttribute('href');
      if (id.length < 2) return;
      var target = document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      var top = target.getBoundingClientRect().top + window.pageYOffset - 68;
      window.scrollTo({ top: top, behavior: reduce ? 'auto' : 'smooth' });
      history.replaceState(null, '', id);
    });
  });

  /* ---------- reveal on scroll ---------- */
  var revealables = document.querySelectorAll('.r');
  if (reduce || !('IntersectionObserver' in window)) {
    document.body.classList.add('no-motion');
    revealables.forEach(function (el) { el.classList.add('in'); });
  } else {
    var ro = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('in');
          ro.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    revealables.forEach(function (el, i) {
      el.style.transitionDelay = Math.min(i % 6, 4) * 45 + 'ms';
      ro.observe(el);
    });
  }

  /* ---------- active section highlight ---------- */
  var links = Array.prototype.slice.call(document.querySelectorAll('.nav a[href^="#"]'));
  var watched = links.map(function (l) { return document.querySelector(l.getAttribute('href')); });

  function setActive() {
    var probe = window.innerHeight * 0.34;
    var current = -1;
    watched.forEach(function (el, i) {
      if (!el) return;
      var r = el.getBoundingClientRect();
      if (r.top <= probe && r.bottom > probe) current = i;
    });
    links.forEach(function (l, i) {
      l.classList.toggle('active', i === current);
      if (i === current) { l.setAttribute('aria-current', 'true'); } else { l.removeAttribute('aria-current'); }
    });
  }
  setActive();
  window.addEventListener('scroll', setActive, { passive: true });
  window.addEventListener('resize', setActive);

  /* ---------- click-to-load video ---------- */
  var vBtn = document.getElementById('videoBtn');
  var vWrap = document.getElementById('videoWrap');
  if (vBtn && vWrap) {
    vBtn.addEventListener('click', function () {
      var iframe = document.createElement('iframe');
      iframe.src = 'https://www.youtube-nocookie.com/embed/0luxUk3VtgA?autoplay=1&rel=0&modestbranding=1';
      iframe.title = 'Quantum Ledger Link — the whole product in two minutes';
      iframe.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';
      iframe.allowFullscreen = true;
      iframe.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
      vWrap.innerHTML = '';
      vWrap.appendChild(iframe);
      iframe.focus();
    });
  }
})();
