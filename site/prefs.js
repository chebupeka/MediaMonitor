// Настройки вида — три кнопки в шапке, без окон и меню:
//   тема — тёмная или светлая «чернила на бумаге»;
//   «Тёплый свет» — только в светлой: меньше синего в бумаге, тексте и точках. Выезжает из-под
//     кнопки темы при наведении или фокусе (на касание — на несколько секунд), включённая видна всегда;
//   версия для слабовидящих (ГОСТ Р 52872-2019) — крупный шрифт, максимальный контраст, без точек,
//     бегущих строк, «расшифровки» и своего курсора.
// Состояние — атрибуты на <html> (data-theme, data-warm, data-lowvision; их же ставит строчка в
// <head> до отрисовки). Выбор хранится в браузере; при первом заходе тема — как в системе, и пока
// человек сам не выбрал, следует за системой. Смена — плавным перетеканием (View Transitions); холст
// (particles.js) и ui.js узнают о смене по событию 'mr-prefs' на document.
(function () {
  'use strict';

  var d = document.documentElement;
  var bTheme = document.querySelector('.pref-theme');
  var bWarm = document.querySelector('.pref-warm');
  var bLow = document.querySelector('.pref-lowvision');
  var wrap = document.querySelector('.prefs-theme');
  if (!bTheme || !bWarm || !bLow) return;

  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) {
    try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* хранилище недоступно — выбор живёт до перезагрузки */ }
  }
  function flag(name, on) { if (on) d.setAttribute(name, ''); else d.removeAttribute(name); }
  function state() {
    return { theme: d.getAttribute('data-theme') === 'light' ? 'light' : 'dark', warm: d.hasAttribute('data-warm'), lowvision: d.hasAttribute('data-lowvision') };
  }
  function sync() {
    var s = state();
    bTheme.setAttribute('aria-pressed', String(s.theme === 'light'));
    bWarm.setAttribute('aria-pressed', String(s.warm));
    bLow.setAttribute('aria-pressed', String(s.lowvision));
  }
  function changed() {
    sync();
    document.dispatchEvent(new CustomEvent('mr-prefs', { detail: state() }));
  }

  // Смена режима — плавным перетеканием за .35 с (styles.css: ::view-transition). Браузер снимает
  // страницу как была и растворяет снимок поверх новой, живой (точки на холсте продолжают
  // двигаться). Так нет пересчёта стилей всей страницы в каждом кадре — переход без провалов.
  // Без View Transitions или при «уменьшить движение» — сразу.
  var reduced = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  function apply(fn) {
    function run() { fn(); changed(); }
    if (reduced || typeof document.startViewTransition !== 'function') { run(); return; }
    document.startViewTransition(run);
  }

  // На касании у кнопки нет фокуса (Safari) — «Тёплый свет» показываем на несколько секунд
  var revealTimer = 0;
  function reveal() {
    wrap.classList.add('reveal');
    clearTimeout(revealTimer);
    revealTimer = setTimeout(function () { wrap.classList.remove('reveal'); }, 4000);
  }

  bTheme.addEventListener('click', function (e) {
    var light = state().theme !== 'light';
    save('mr-theme', light ? 'light' : 'dark');
    apply(function () { d.setAttribute('data-theme', light ? 'light' : 'dark'); });
    if (light && e.pointerType && e.pointerType !== 'mouse') reveal();
  });
  bWarm.addEventListener('click', function () {
    var on = !state().warm;
    save('mr-warm', on ? '1' : null);
    apply(function () { flag('data-warm', on); });
  });
  bLow.addEventListener('click', function () {
    var on = !state().lowvision;
    save('mr-lowvision', on ? '1' : null);
    apply(function () { flag('data-lowvision', on); });
  });

  // Пока человек не выбрал тему сам — она следует за системой
  var mq = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)');
  if (mq) {
    var follow = function (e) {
      if (load('mr-theme')) return;
      apply(function () { d.setAttribute('data-theme', e.matches ? 'light' : 'dark'); });
    };
    if (mq.addEventListener) mq.addEventListener('change', follow); else if (mq.addListener) mq.addListener(follow);
  }

  sync();
})();
