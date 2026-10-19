// «Стрежень» — вариант «Частицы»: интерфейс.
// Расшифровка текста, бегущие строки, свой курсор, меню, индикатор прокрутки.

(function () {
  'use strict';

  var doc = document.documentElement;
  var reduced = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  doc.classList.add('js');

  /* ---------- Расшифровка текста ---------- */
  // Строка проявляется слева направо; на переднем крае несколько знаков
  // мелькают случайными символами. Ещё не проявленная часть прозрачна и держит место.

  var UP = 'АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЭЮЯ0123456789#%&*+=/<>';
  var LO = 'абвгдежзиклмнопрстуфхцчшэюя0123456789#%&*+=/<>';

  function prepare(el) {
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
    var nodes = [], parts = [], total = 0;
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (tn) {
      var s = tn.nodeValue.replace(/\s+/g, ' ');
      if (!s) return;
      var w = document.createElement('span');
      var a = document.createElement('span');
      var b = document.createElement('span');
      var c = document.createElement('span');
      b.className = 'sc-b';
      c.className = 'sc-c';
      c.textContent = s;
      w.appendChild(a); w.appendChild(b); w.appendChild(c);
      tn.parentNode.replaceChild(w, tn);
      // ia, ib — где сейчас граница проявленного и мелькающего; mixing — есть мелькающие знаки
      parts.push({ s: s, w: w, a: a, b: b, c: c, start: total, ia: 0, ib: 0, mixing: false });
      total += s.length;
    });
    el._sc = { parts: parts, total: total };
  }

  // Возвращает обычные текстовые узлы, чтобы скринридеры и выделение работали как обычно
  function finish(el) {
    if (!el._sc) return;
    el._sc.parts.forEach(function (p) {
      if (p.w.parentNode) p.w.parentNode.replaceChild(document.createTextNode(p.s), p.w);
    });
    el._sc = null;
  }

  // Меняет в DOM только то, что изменилось: раньше на каждом шаге переписывались все
  // кусочки текста элемента, и браузер заново раскладывал и перерисовывал весь абзац
  function render(el, n, front) {
    var parts = el._sc.parts;
    for (var k = 0; k < parts.length; k++) {
      var p = parts[k], L = p.s.length, i0 = n - p.start;
      var ia = Math.max(0, Math.min(L, i0)), ib = Math.max(0, Math.min(L, i0 + front));
      if (ia !== p.ia) { p.a.textContent = p.s.slice(0, ia); p.ia = ia; }
      if (ib !== p.ib) { p.c.textContent = p.s.slice(ib); p.ib = ib; }
      if (ib > ia || p.mixing) {
        var r = '';
        for (var i = ia; i < ib; i++) {
          var ch = p.s[i];
          if (ch === ' ') { r += ' '; continue; }
          var set = ch === ch.toLowerCase() && ch !== ch.toUpperCase() ? LO : UP;
          r += set[(Math.random() * set.length) | 0];
        }
        p.b.textContent = r;
        p.mixing = ib > ia;
      }
    }
  }

  var running = [];
  var scRaf = 0, scLast = 0;

  function scramble(el, opts) {
    if (reduced) return;
    opts = opts || {};
    if (!el._sc) prepare(el);
    running = running.filter(function (x) { return x.el !== el; });
    running.push({
      el: el,
      t0: performance.now() + (opts.delay || 0),
      dur: opts.dur || Math.max(450, Math.min(1900, el._sc.total * 24)),
      front: opts.front || 5
    });
    if (!scRaf) scRaf = requestAnimationFrame(scStep);
  }

  function scStep(now) {
    scRaf = 0;
    var tick = now - scLast > 40; // случайные знаки меняются ~25 раз в секунду
    if (tick) scLast = now;
    running = running.filter(function (x) {
      if (now < x.t0) return true;
      var p = (now - x.t0) / x.dur;
      if (p >= 1) { finish(x.el); return false; }
      if (tick) render(x.el, Math.floor(p * x.el._sc.total), x.front);
      return true;
    });
    if (running.length) scRaf = requestAnimationFrame(scStep);
  }

  var scrambles = Array.prototype.slice.call(document.querySelectorAll('[data-scramble]'));

  /* ---------- Появление при прокрутке ---------- */

  var fades = document.querySelectorAll('.fade, .cmp-row, .faq details');
  var counters = Array.prototype.slice.call(document.querySelectorAll('[data-count]'));

  // Полосы хода поиска: до какой доли заполнятся (CSS берёт --fill, когда строка появилась)
  Array.prototype.forEach.call(document.querySelectorAll('[data-fill]'), function (el) {
    el.style.setProperty('--fill', el.getAttribute('data-fill') + '%');
  });

  // Счётчик набегает от нуля до числа из разметки (без JS там сразу итоговое число)
  function countUp(el) {
    var to = Number(el.getAttribute('data-count')) || 0, t0 = performance.now(), dur = 1100 + to * 40, shown = '';
    (function tick(now) {
      var p = Math.min(1, (now - t0) / dur);
      var v = String(Math.round(to * (1 - Math.pow(1 - p, 3))));
      if (v !== shown) { shown = v; el.textContent = v; } // число не изменилось — DOM не трогаем
      if (p < 1) requestAnimationFrame(tick);
    })(t0);
  }

  if (reduced || !('IntersectionObserver' in window)) {
    Array.prototype.forEach.call(fades, function (el) { el.classList.add('in'); });
  } else {
    scrambles.forEach(prepare);
    counters.forEach(function (el) { el.textContent = '0'; });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        var el = e.target;
        io.unobserve(el);
        if (el.hasAttribute('data-scramble')) {
          scramble(el, {
            delay: Number(el.getAttribute('data-delay')) || 0,
            front: Number(el.getAttribute('data-front')) || 5,
            dur: Number(el.getAttribute('data-dur')) || 0
          });
        } else if (el.hasAttribute('data-count')) {
          countUp(el);
        } else {
          el.classList.add('in');
        }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.15 });
    scrambles.forEach(function (el) { io.observe(el); });
    counters.forEach(function (el) { io.observe(el); });
    Array.prototype.forEach.call(fades, function (el) { io.observe(el); });
  }

  // Повторная расшифровка при наведении на ссылки
  Array.prototype.forEach.call(document.querySelectorAll('[data-hover]'), function (el) {
    el.addEventListener('mouseenter', function () {
      if (el._sc) return; // ещё идёт первая расшифровка
      scramble(el, { dur: 420, front: 3 });
    });
  });

  // Ответ в вопросах проявляется при раскрытии
  Array.prototype.forEach.call(document.querySelectorAll('.faq details'), function (d) {
    d.addEventListener('toggle', function () {
      var p = d.querySelector('p');
      if (d.open && p) scramble(p, { dur: 700 });
    });
  });

  /* ---------- Бегущие строки ---------- */

  // Копий строки — столько, чтобы лента всегда перекрывала окно (обычно две). Раньше их было
  // четыре: слой ленты выходил шириной в десятки тысяч пикселей и его дольше перерисовывать.
  var marquees = Array.prototype.map.call(document.querySelectorAll('.marquee'), function (m) {
    var track = m.querySelector('.marquee-track');
    return { m: m, track: track, html: track.innerHTML, copies: 1, speed: Number(m.getAttribute('data-speed')) || 0.5, w: 1, top: 0, h: 0, x: '' };
  });

  function measureMarquees() {
    marquees.forEach(function (q) {
      var w = q.track.scrollWidth / q.copies || 1;
      var need = Math.max(2, Math.ceil(window.innerWidth / w) + 1);
      if (need !== q.copies) {
        q.copies = need;
        q.track.innerHTML = new Array(need + 1).join(q.html);
      }
      q.w = w;
      q.top = q.m.getBoundingClientRect().top + window.scrollY;
      q.h = q.m.offsetHeight;
    });
  }

  /* ---------- Курсор ---------- */

  var ring = document.querySelector('.cur-ring');
  var dot = document.querySelector('.cur-dot');
  var cursorOn = !reduced && window.matchMedia && window.matchMedia('(pointer: fine)').matches;
  var cur = { x: -100, y: -100, rx: -100, ry: -100, moved: false };

  if (cursorOn) {
    doc.classList.add('has-cursor');
    ring.style.transform = 'translate(-100px,-100px)'; // пока мышь не двигалась — за краем окна
    // Точка курсора переставляется в кадре (тот же кадр, что и событие): несколько событий
    // мыши за кадр — одна запись стиля
    window.addEventListener('pointermove', function (e) {
      cur.x = e.clientX;
      cur.y = e.clientY;
      cur.moved = true;
    }, { passive: true });
    document.addEventListener('pointerover', function (e) {
      ring.classList.toggle('big', !!(e.target.closest && e.target.closest('a, button, summary')));
    });
    document.addEventListener('pointerleave', function () { cur.x = cur.y = -100; });
  }

  /* ---------- Меню ---------- */

  var burger = document.querySelector('.burger');
  var menu = document.getElementById('menu');

  function setMenu(open) {
    doc.classList.toggle('menu-open', open);
    burger.setAttribute('aria-expanded', String(open));
    burger.setAttribute('aria-label', open ? 'Закрыть меню' : 'Открыть меню');
    menu.setAttribute('aria-hidden', String(!open));
    if (open) {
      Array.prototype.forEach.call(menu.querySelectorAll('.menu-nav a'), function (a, i) {
        scramble(a, { delay: 250 + i * 70, dur: 650, front: 4 });
      });
    }
  }
  burger.addEventListener('click', function () { setMenu(!doc.classList.contains('menu-open')); });
  menu.addEventListener('click', function (e) { if (e.target.closest('a')) setMenu(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && doc.classList.contains('menu-open')) { setMenu(false); burger.focus(); } });

  /* ---------- Кадр: строки, курсор, индикатор ---------- */

  // В кадре — только запись: прокрутка, высота страницы и места строк запоминаются в
  // обработчиках и при изменении размеров. Раньше кадр читал scrollY и scrollHeight после
  // записи transform — браузер каждый кадр досчитывал стили и раскладку.
  var bar = document.querySelector('.progress-bar');
  var progress = document.querySelector('.progress');
  var scrollTop = window.scrollY, vh = window.innerHeight, maxScroll = 0, lastScroll = -1e9;
  window.addEventListener('scroll', function () { scrollTop = window.scrollY; lastScroll = performance.now(); }, { passive: true });

  function measurePage() {
    vh = window.innerHeight;
    maxScroll = document.documentElement.scrollHeight - vh;
    measureMarquees();
  }

  var sy = scrollTop;
  var t0 = performance.now();
  var last = t0;
  var barShown = -1, scrolling = false;
  // Доля сближения за кадр, пересчитанная на реальное время: при 60 кадрах/с — k
  function ease(k, dt) { return 1 - Math.pow(1 - k, dt * 60); }

  function frame(now) {
    requestAnimationFrame(frame);
    var dt = Math.min(1, Math.max(0, (now - last) / 1000));
    last = now;
    sy += (scrollTop - sy) * (reduced ? 1 : ease(0.085, dt));

    if (!reduced) {
      var drift = (now - t0) / 1000 * 24; // лёгкое собственное движение строки
      for (var k = 0; k < marquees.length; k++) {
        var q = marquees[k];
        if (q.top + q.h < scrollTop - 50 || q.top > scrollTop + vh + 50) continue; // строка за экраном — не двигаем
        var off = (sy - q.top + vh) * q.speed + drift * Math.sign(q.speed);
        var x = (-(((off % q.w) + q.w) % q.w)).toFixed(1);
        if (x !== q.x) { q.x = x; q.track.style.transform = 'translate3d(' + x + 'px,0,0)'; }
      }
    }

    if (cursorOn) {
      if (cur.moved) { cur.moved = false; dot.style.transform = 'translate(' + cur.x + 'px,' + cur.y + 'px)'; }
      var dx = cur.x - cur.rx, dy = cur.y - cur.ry;
      if (dx * dx + dy * dy > 0.01) { // кольцо догнало курсор — не перерисовываем
        cur.rx += dx * ease(0.16, dt);
        cur.ry += dy * ease(0.16, dt);
        ring.style.transform = 'translate(' + cur.rx.toFixed(1) + 'px,' + cur.ry.toFixed(1) + 'px)';
      }
    }

    var p = maxScroll > 0 ? Math.min(1, scrollTop / maxScroll) : 0;
    if (p !== barShown) { barShown = p; bar.style.strokeDashoffset = String(1 - p); }
    // Пока страницу листают, на узком экране кнопка «наверх» прячется (styles.css)
    var sc = now - lastScroll < 700;
    if (sc !== scrolling) { scrolling = sc; progress.classList.toggle('is-scrolling', sc); }
  }

  measurePage();
  window.addEventListener('resize', measurePage);
  window.addEventListener('load', measurePage);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(measurePage);
  // Высота страницы меняется при раскрытии вопросов и подгрузке шрифтов
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(measurePage).observe(document.body);
  requestAnimationFrame(frame);
})();
