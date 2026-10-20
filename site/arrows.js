// Две белые стрелки из точек к кнопке «Установить «Медиарадар»».
//
// Рисуются на своём холсте внутри раздела «Установка», а не на общем холсте частиц
// (particles.js). Общий холст закреплён на экране и перерисовывается кадрами, а страницу
// браузер прокручивает отдельно — при резкой прокрутке стрелки на нём отставали от кнопки
// и дёргались. Этот холст — часть страницы и едет вместе с кнопкой без задержки.
//
// Положение стрелок считается по строкам самой ссылки: на широком экране они приходят справа
// сверху и справа снизу к концам строк, на узком — сверху вниз к ссылке. Собираются из точек
// так же, как формы общего холста: по прокрутке — пока раздел въезжает на экран, рассеянные
// точки слетаются с разлётом по дуге и к моменту, когда ссылка в центре, стрелки готовы;
// при прокрутке назад рассыпаются. По готовым стрелкам к остриям бегут импульсы.
//
// Точки рисует WebGL: положение, яркость, импульсы и отталкивание от курсора считаются в
// шейдере по тем же формулам, что были в цикле canvas 2D (тот остался запасным путём без
// WebGL). Каждый кадр — одна команда рисования вместо 7 000 fillRect: раньше у раздела
// «Установка» кадр стоил ~4 мс скрипта и столько же работы видеокарты, и прокрутка проседала
// до 44 кадров/с. Края квадратиков сглаживаются так же, как у fillRect (доля пикселя под
// квадратиком), сложение — как у 'lighter'.
//
// В кадре раскладка не читается: прокрутка запоминается в обработчике scroll, место раздела —
// в layout() (при изменении размеров и раз в секунду, как и раньше).
(function () {
  'use strict';

  var section = document.getElementById('install');
  var link = section && section.querySelector('.giant a');
  if (!section || !link) return;

  var reduced = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var coarse = Math.min(screen.width, screen.height) < 700;

  var canvas = document.createElement('canvas');
  canvas.className = 'install-arrows';
  canvas.setAttribute('aria-hidden', 'true');
  // Положение задаём здесь, а не только в CSS: если холст окажется в потоке (например, браузер
  // взял старый styles.css из кэша), он раздвинет раздел, ResizeObserver увеличит холст — и так
  // без конца, пока холст не станет непомерным
  canvas.style.cssText = 'position:absolute;left:0;top:0;pointer-events:none;z-index:0;display:block;';
  if (getComputedStyle(section).position === 'static') section.style.position = 'relative';
  var content = section.querySelector('.wide'); // текст раздела — над холстом
  if (content) { content.style.position = 'relative'; content.style.zIndex = '1'; }
  section.insertBefore(canvas, section.firstChild);
  var gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: false, depth: false });
  var ctx = gl ? null : canvas.getContext('2d');
  if (!gl && !ctx) return;

  // TOP — насколько холст выступает над разделом: хвосты стрелок бывают выше его начала
  var W = 0, H = 0, TOP = 0, dpr = 1, pts = [], visible = false, raf = 0, key = '';
  var from = 0, to = 1;           // прокрутка, на которой сборка начинается и заканчивается
  var sp = window.scrollY, last = 0, checkedAt = 0; // сглаженная прокрутка — как sy в particles.js
  // Прокрутка, высота окна и место раздела в документе — запоминаются, в кадре не читаются
  var scrollTop = window.scrollY, VH = window.innerHeight, secTop = 0, secLeft = 0;
  window.addEventListener('scroll', function () { scrollTop = window.scrollY; }, { passive: true });

  // Цвет и смешивание — по теме (styles.css: --dot-arrow, --dot-blend, --dots): белые светящиеся
  // стрелки на тёмном, тушь на бумаге. Смена темы — плавно за .35 с; у слабовидящих стрелок нет.
  var root = document.documentElement;
  function readLook() {
    var cs = getComputedStyle(root), v = cs.getPropertyValue('--dot-arrow').trim(), c = [0.933, 0.949, 1];
    if (/^#[0-9a-f]{6}$/i.test(v)) c = [parseInt(v.slice(1, 3), 16) / 255, parseInt(v.slice(3, 5), 16) / 255, parseInt(v.slice(5, 7), 16) / 255];
    return { c: c, normal: cs.getPropertyValue('--dot-blend').trim() === 'normal', on: cs.getPropertyValue('--dots').trim() !== 'off' };
  }
  var lookTo = readLook(), lookFrom = lookTo, lookT0 = -1e9, col = lookTo.c.slice(), normal = lookTo.normal, dip = 1;
  function updateLook(now) {
    var x = reduced ? 1 : Math.max(0, Math.min(1, (now - lookT0) / 350)), k = x * x * (3 - 2 * x);
    for (var i = 0; i < 3; i++) col[i] = lookFrom.c[i] + (lookTo.c[i] - lookFrom.c[i]) * k;
    normal = x < 0.5 ? lookFrom.normal : lookTo.normal;
    dip = lookFrom.normal !== lookTo.normal ? 1 - 0.92 * Math.sin(Math.PI * x) : 1;
    return x < 1;
  }

  // Курсор: точки рядом с ним расступаются — как на общем холсте (particles.js, uMouse).
  // Координаты экранные, сглаженные; без мыши (палец, вне окна) — далеко за экраном.
  var FAR = -1e5, mouse = { x: FAR, y: FAR, tx: FAR, ty: FAR };
  window.addEventListener('pointermove', function (e) {
    if (e.pointerType !== 'mouse') return;
    mouse.tx = e.clientX; mouse.ty = e.clientY;
    if (mouse.x === FAR) { mouse.x = mouse.tx; mouse.y = mouse.ty; } // первое касание — без пролёта через экран
  }, { passive: true });
  document.addEventListener('pointerleave', function () { mouse.tx = mouse.ty = mouse.x = mouse.y = FAR; });

  // Случайные числа с семенем: одна и та же раскладка точек при каждой сборке
  function rng(seed) {
    return function () {
      seed |= 0; seed = seed + 0x6d2b79f5 | 0;
      var t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  var R = rng(41);
  function gauss() { var u = R() || 1e-6, v = R(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }

  // Строки ссылки — прямоугольники букв, сгруппированные по строкам, в координатах раздела.
  // Не getClientRects() самой ссылки: пока идёт «расшифровка» (ui.js), текст разбит на служебные
  // фрагменты, и первым может оказаться пустой кусочек в начале строки.
  function textLines(origin) {
    var range = document.createRange(), lines = [];
    range.selectNodeContents(link);
    Array.prototype.forEach.call(range.getClientRects(), function (r) {
      if (r.width < 1 || r.height < 1) return;
      var top = r.top - origin.top, bottom = r.bottom - origin.top, left = r.left - origin.left, right = r.right - origin.left;
      var line = lines.filter(function (l) { return Math.abs(l.top - top) < r.height * 0.5; })[0];
      if (!line) lines.push({ top: top, bottom: bottom, left: left, right: right });
      else {
        line.top = Math.min(line.top, top); line.bottom = Math.max(line.bottom, bottom);
        line.left = Math.min(line.left, left); line.right = Math.max(line.right, right);
      }
    });
    lines.sort(function (a, b) { return a.top - b.top; });
    lines.forEach(function (l) { l.height = l.bottom - l.top; l.width = l.right - l.left; });
    return lines;
  }

  function inside(poly, x, y) {
    var inn = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      var a = poly[i], b = poly[j];
      if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) inn = !inn;
    }
    return inn;
  }

  // Контур стрелки от хвоста s к острию t: хвост 0.34 длины, к шее (0.68) сужается до 0.17,
  // наконечник 0.42
  function arrowShape(s, t) {
    var dx = t[0] - s[0], dy = t[1] - s[1], L = Math.sqrt(dx * dx + dy * dy) || 1;
    var ax = dx / L, ay = dy / L, nx = -ay, ny = ax;
    function at(u, v) { return [s[0] + (ax * u + nx * v) * L, s[1] + (ay * u + ny * v) * L]; }
    var poly = [at(0, -0.17), at(0.68, -0.085), at(0.68, -0.21), [t[0], t[1]], at(0.68, 0.21), at(0.68, 0.085), at(0, 0.17)];
    var box = [Infinity, Infinity, -Infinity, -Infinity], edges = [], total = 0;
    poly.forEach(function (p, i) {
      var q = poly[(i + 1) % poly.length], len = Math.sqrt((q[0] - p[0]) * (q[0] - p[0]) + (q[1] - p[1]) * (q[1] - p[1]));
      box = [Math.min(box[0], p[0]), Math.min(box[1], p[1]), Math.max(box[2], p[0]), Math.max(box[3], p[1])];
      edges.push({ a: p, b: q, from: total, len: len });
      total += len;
    });
    return { s: s, ax: ax, ay: ay, L: L, poly: poly, box: box, edges: edges, total: total };
  }

  function onEdge(sh) {
    var d = R() * sh.total, e = sh.edges[sh.edges.length - 1];
    for (var i = 0; i < sh.edges.length; i++) if (sh.edges[i].from + sh.edges[i].len >= d) { e = sh.edges[i]; break; }
    var f = (d - e.from) / (e.len || 1);
    return [e.a[0] + (e.b[0] - e.a[0]) * f, e.a[1] + (e.b[1] - e.a[1]) * f];
  }

  // Где стрелки: хвост и остриё каждой, в координатах раздела
  function aim() {
    var origin = section.getBoundingClientRect();
    var lines = textLines(origin);
    if (!lines.length) return null;
    var first = lines[0], last = lines[lines.length - 1];
    var vw = window.innerWidth, vh = window.innerHeight;
    var gap = Math.max(24, vw * 0.025), right = Math.max(first.right, last.right), room = W - right;
    if (room > Math.max(vw * 0.2, 220)) {
      // Справа есть место: сверху справа к первой строке, снизу справа ко второй. По вертикали —
      // между шапкой сайта (когда ссылка в центре экрана) и линией над колонками подвала.
      var cols = section.querySelector('.foot-cols');
      var floor = cols ? cols.getBoundingClientRect().top - origin.top - 24 : H - 40;
      var ceil = (first.top + last.bottom) / 2 - vh / 2 + 96;
      var y1 = first.top + first.height * 0.5, y2 = last.top + last.height * 0.55;
      var x1 = first.right + gap, x2 = last.right + gap, reach = Math.min(room * 0.62, vh * 0.42);
      var up = Math.min(reach * 0.7, (y1 - ceil) * 0.78), down = Math.min(reach * 0.55, (floor - y2) * 0.58);
      return [[[x1 + reach * 0.9, y1 - up], [x1, y1]], [[x2 + reach * 0.9, y2 + down], [x2, y2]]];
    }
    // Узко: сверху вниз к ссылке, острия — над подписью «Готовы попробовать?»
    var label = section.querySelector('.label');
    var top = label ? Math.min(first.top, label.getBoundingClientRect().top - origin.top) : first.top;
    var y = top - gap * 0.8, a = first.left + first.width * 0.27, b = first.left + first.width * 0.75;
    return [[[a - vw * 0.06, y - vh * 0.24], [a, y]], [[b + vw * 0.06, y - vh * 0.24], [b, y]]];
  }

  // Точки: плотная грань и контур. u — место вдоль стрелки (0 — хвост, 1 — остриё) для импульсов.
  function build(list) {
    R = rng(41);
    var shapes = list.map(function (g) { return arrowShape(g[0], g[1]); });
    var area = shapes.reduce(function (sum, sh) { return sum + sh.L * sh.L * 0.2; }, 0);
    var n = Math.round(Math.min(coarse ? 3200 : 7000, Math.max(1200, area / 10)));
    pts = [];
    for (var i = 0; i < n; i++) {
      var sh = shapes[i % shapes.length], x, y, edge = R() < 0.2;
      if (edge) {
        var e = onEdge(sh); x = e[0] + gauss() * 1.1; y = e[1] + gauss() * 1.1;
      } else {
        for (var k = 0; k < 60; k++) {
          x = sh.box[0] + R() * (sh.box[2] - sh.box[0]); y = sh.box[1] + R() * (sh.box[3] - sh.box[1]);
          if (inside(sh.poly, x, y)) break;
        }
      }
      pts.push(dot(x, y, ((x - sh.s[0]) * sh.ax + (y - sh.s[1]) * sh.ay) / sh.L, !edge && R() < 0.22,
        edge ? 0.95 : 0.55 + R() * 0.4, (edge ? 1.6 : 1.3 + R() * 1.1) * (R() < 0.04 ? 1.8 : 1)));
    }
    // Свечение у остриёв
    shapes.forEach(function (sh) {
      for (var j = 0; j < 40; j++) pts.push(dot(sh.poly[3][0] + gauss() * 7, sh.poly[3][1] + gauss() * 7, 1, false, 0.5, 1.8));
    });
    upload();
  }

  // Значение в пределах холста. Выпавшее за край — в случайное место внутри, а не прижатое
  // к краю: иначе такие точки выстраиваются вдоль края в заметную линию.
  function within(v, lo, hi) { return v >= lo && v <= hi ? v : lo + R() * (hi - lo); }

  // Точка стрелки: где она в собранной стрелке (x, y), откуда прилетает (sx, sy — рассеяна выше,
  // там, где был предыдущий раздел), куда отлетает по дуге в пути (bx, by) и когда трогается (d)
  function dot(x, y, u, flow, a, size) {
    var vh = window.innerHeight, ang = R() * Math.PI * 2, burst = 20 + R() * 70;
    return {
      x: x, y: y, u: u, flow: flow, a: a, s: size, ph: R() * Math.PI * 2,
      sx: within(x + gauss() * W * 0.18, 8, W - 8),
      sy: within(y - (0.15 + R() * 0.6) * vh, -TOP + 8, H - 8),
      bx: Math.cos(ang) * burst, by: Math.sin(ang) * burst,
      d: R()
    };
  }

  // Самый большой холст, который точно выделится: не больше 16 млн пикселей и 3 экранов в высоту
  var MAX_PIXELS = 16e6;

  function layout() {
    var w = section.clientWidth, h = Math.min(section.clientHeight, window.innerHeight * 3);
    if (!w || !h) return;
    var list;
    W = w; H = h; TOP = Math.round(window.innerHeight * 0.5);
    // Сборка: от момента, когда верх раздела показался снизу экрана, до ссылки в центре экрана.
    // Считаем при каждом измерении: раздел мог сдвинуться, даже если сам не изменился.
    var origin = section.getBoundingClientRect(), vh = window.innerHeight, lr = link.getBoundingClientRect();
    VH = vh; secTop = origin.top + window.scrollY; secLeft = origin.left + window.scrollX;
    var bottom = document.documentElement.scrollHeight - vh;
    from = origin.top + window.scrollY - vh;
    to = Math.max(from + 1, Math.min(bottom, lr.top + window.scrollY + lr.height / 2 - vh / 2));
    list = aim();
    if (!list) return;
    var next = JSON.stringify([W, H, TOP, list.map(function (g) { return g.map(function (p) { return p.map(Math.round); }); })]);
    if (next === key) return;
    key = next;
    dpr = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(MAX_PIXELS / (W * (H + TOP))));
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round((H + TOP) * dpr);
    canvas.style.width = W + 'px';
    canvas.style.height = H + TOP + 'px';
    canvas.style.top = -TOP + 'px';
    build(list);
    draw(performance.now());
  }

  function smoothstep(v) { v = Math.max(0, Math.min(1, v)); return v * v * (3 - 2 * v); }

  /* ---------- WebGL: те же формулы, что в draw2d, — в шейдере ---------- */

  // Точка: a0 = (x, y, sx, sy), a1 = (bx, by, d, u), a2 = (flow, a, s, ph) — как поля dot()
  var VS = [
    'attribute vec4 a0;',
    'attribute vec4 a1;',
    'attribute vec4 a2;',
    'uniform float uK, uT, uMotion, uDpr, uTop, uReach, uPush;',
    'uniform vec2 uMouse, uView;',
    'varying vec2 vC;',
    'varying float vH, vA;',
    'float sm(float v) { v = clamp(v, 0.0, 1.0); return v * v * (3.0 - 2.0 * v); }',
    'void main() {',
    '  float e = sm((uK - a1.z * 0.3) / 0.7), arc = sin(3.141592653589793 * e);',
    '  float a = a2.y * (0.22 + 0.78 * e);',
    '  if (uMotion > 0.5) {',
    '    if (a2.x > 0.5) { float w = fract(a1.w * 5.0 - uT * 0.42); a *= 1.0 - e + e * (0.25 + 1.2 * pow(w, 6.0)); }',
    '    a *= 0.82 + 0.18 * sin(uT * 2.1 + a2.w);',
    '  }',
    '  vec2 p = a0.zw + (a0.xy - a0.zw) * e + a1.xy * arc;',
    '  vec2 dm = p - uMouse; float d2 = dot(dm, dm);',
    '  if (d2 < uReach * uReach && d2 > 0.25) { float d = sqrt(d2); p += dm / d * (uPush * sm(1.0 - d / uReach)); }',
    '  vec2 px = vec2(p.x, p.y + uTop) * uDpr;', // пиксели холста, отсчёт сверху
    '  vC = vec2(px.x, uView.y - px.y);', // то же в отсчёте gl_FragCoord (снизу)
    '  vH = a2.z * uDpr * 0.5;',
    '  vA = min(1.0, a);',
    '  gl_Position = vec4(px.x / uView.x * 2.0 - 1.0, 1.0 - px.y / uView.y * 2.0, 0.0, 1.0);',
    '  gl_PointSize = ceil(vH * 2.0) + 2.0;', // запас в пиксель на сглаженный край
    '}'
  ].join('\n');
  // Доля пикселя под квадратиком — как сглаживание края у fillRect; цвет #eef2ff
  var FS = [
    '#ifdef GL_FRAGMENT_PRECISION_HIGH',
    'precision highp float;', // координаты пикселей до нескольких тысяч
    '#else',
    'precision mediump float;',
    '#endif',
    'uniform vec3 uColor;',
    'uniform float uDip;',
    'varying vec2 vC;',
    'varying float vH, vA;',
    'void main() {',
    '  vec2 lo = max(gl_FragCoord.xy - 0.5, vC - vH), hi = min(gl_FragCoord.xy + 0.5, vC + vH);',
    '  vec2 cov = clamp(hi - lo, 0.0, 1.0);',
    '  float a = vA * cov.x * cov.y * uDip;',
    '  if (a <= 0.0) discard;',
    '  gl_FragColor = vec4(uColor * a, a);',
    '}'
  ].join('\n');

  var prog = null, U = {}, buf = null, count = 0, loc = [];
  function initGL() {
    function sh(type, src) {
      var o = gl.createShader(type);
      gl.shaderSource(o, src);
      gl.compileShader(o);
      if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(o));
      return o;
    }
    prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    ['uK', 'uT', 'uMotion', 'uDpr', 'uTop', 'uReach', 'uPush', 'uMouse', 'uView', 'uColor', 'uDip'].forEach(function (n) { U[n] = gl.getUniformLocation(prog, n); });
    loc = ['a0', 'a1', 'a2'].map(function (n) { return gl.getAttribLocation(prog, n); });
    buf = gl.createBuffer();
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE); // сложение — как globalCompositeOperation 'lighter' (тёмная тема)
    gl.clearColor(0, 0, 0, 0);
  }
  if (gl) {
    try { initGL(); } catch (err) { console.error(err); return; }
    canvas.addEventListener('webglcontextlost', function (e) { e.preventDefault(); prog = null; });
    canvas.addEventListener('webglcontextrestored', function () {
      try { initGL(); upload(); draw(performance.now()); } catch (err) { console.error(err); }
    });
  }

  // Точки — в буфер видеокарты: один раз на сборку (build), а не каждый кадр
  function upload() {
    if (!gl || !prog) return;
    var a = new Float32Array(pts.length * 12);
    for (var i = 0; i < pts.length; i++) {
      var p = pts[i], o = i * 12;
      a[o] = p.x; a[o + 1] = p.y; a[o + 2] = p.sx; a[o + 3] = p.sy;
      a[o + 4] = p.bx; a[o + 5] = p.by; a[o + 6] = p.d; a[o + 7] = p.u;
      a[o + 8] = p.flow ? 1 : 0; a[o + 9] = p.a; a[o + 10] = p.s; a[o + 11] = p.ph;
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, a, gl.STATIC_DRAW);
    count = pts.length;
  }

  function clearCanvas() {
    if (gl) { gl.viewport(0, 0, canvas.width, canvas.height); gl.clear(gl.COLOR_BUFFER_BIT); return; }
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }

  function draw(now) {
    var t = now / 1000;
    updateLook(now);
    // Прогресс сборки, как в particles.js: у краёв диапазона форма держится собранной или рассыпанной
    var k = reduced ? 1 : Math.max(0, Math.min(1, ((sp - from) / (to - from) - 0.1) / 0.75));
    // Курсор в координатах раздела; радиус и сила — как в шейдере общего холста
    // (0.28 и 0.05 в единицах половины высоты экрана). Место раздела — запомненное.
    var vh = VH, mx = mouse.x - secLeft, my = mouse.y - (secTop - scrollTop), reach = vh * 0.14, push = vh * 0.025;
    if (gl) {
      if (!prog) return;
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clear(gl.COLOR_BUFFER_BIT);
      if (!count || !lookTo.on) return;
      gl.useProgram(prog);
      // светлая тема — обычное наложение (тушь), тёмная — сложение (свечение)
      if (normal) gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA); else gl.blendFunc(gl.ONE, gl.ONE);
      gl.uniform3f(U.uColor, col[0], col[1], col[2]);
      gl.uniform1f(U.uDip, dip);
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      for (var j = 0; j < 3; j++) {
        gl.enableVertexAttribArray(loc[j]);
        gl.vertexAttribPointer(loc[j], 4, gl.FLOAT, false, 48, j * 16);
      }
      gl.uniform1f(U.uK, k);
      gl.uniform1f(U.uT, t % 3600); // время по модулю часа: точность float в шейдере
      gl.uniform1f(U.uMotion, reduced ? 0 : 1);
      gl.uniform1f(U.uDpr, dpr);
      gl.uniform1f(U.uTop, TOP);
      gl.uniform1f(U.uReach, reach);
      gl.uniform1f(U.uPush, push);
      gl.uniform2f(U.uMouse, mx, my);
      gl.uniform2f(U.uView, canvas.width, canvas.height);
      gl.drawArrays(gl.POINTS, 0, count);
      return;
    }
    draw2d(t, k, mx, my, reach, push);
  }

  // Запасной путь без WebGL — прежняя отрисовка canvas 2D
  function draw2d(t, k, mx, my, reach, push) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, TOP * dpr); // точки — в координатах раздела
    ctx.clearRect(0, -TOP, W, H + TOP);
    if (!lookTo.on) return;
    ctx.globalCompositeOperation = normal ? 'source-over' : 'lighter';
    ctx.fillStyle = 'rgb(' + Math.round(col[0] * 255) + ',' + Math.round(col[1] * 255) + ',' + Math.round(col[2] * 255) + ')';
    for (var i = 0; i < pts.length; i++) {
      var p = pts[i];
      var e = smoothstep((k - p.d * 0.3) / 0.7), arc = Math.sin(Math.PI * e);
      var a = p.a * (0.22 + 0.78 * e); // в пути точки тусклее — как рассеянное облако
      if (!reduced) {
        if (p.flow) { var w = (p.u * 5 - t * 0.42) % 1; if (w < 0) w += 1; a *= 1 - e + e * (0.25 + 1.2 * Math.pow(w, 6)); }
        a *= 0.82 + 0.18 * Math.sin(t * 2.1 + p.ph);
      }
      var x = p.sx + (p.x - p.sx) * e + p.bx * arc, y = p.sy + (p.y - p.sy) * e + p.by * arc;
      var dx = x - mx, dy = y - my, d2 = dx * dx + dy * dy;
      if (d2 < reach * reach && d2 > 0.25) {
        var d = Math.sqrt(d2), f = push * smoothstep(1 - d / reach);
        x += dx / d * f; y += dy / d * f;
      }
      ctx.globalAlpha = Math.min(1, a) * dip;
      ctx.fillRect(x - p.s / 2, y - p.s / 2, p.s, p.s);
    }
    ctx.globalAlpha = 1;
  }

  function loop(now) {
    raf = 0;
    if (!visible) return;
    if (!lookTo.on && now - lookT0 > 400) { draw(now); return; } // погасли — стоим
    var dt = Math.min(1, Math.max(0, (now - last) / 1000));
    last = now;
    sp += (scrollTop - sp) * (1 - Math.pow(1 - 0.085, dt * 60));
    var m = 1 - Math.pow(1 - 0.25, dt * 60);
    mouse.x += (mouse.tx - mouse.x) * m; mouse.y += (mouse.ty - mouse.y) * m;
    // раз в секунду сверяем положение ссылки: её «расшифровывают», раздел мог сдвинуться
    if (now - checkedAt > 1000) { checkedAt = now; layout(); }
    draw(now);
    raf = requestAnimationFrame(loop);
  }

  function start() {
    if (raf || reduced) return;
    // Не «доезжаем» от старого положения, если раздел долго был за экраном. Но если прыжком перескочили
    // начало сборки — собираемся из рассеянного облака, как формы общего холста при резкой прокрутке
    sp = Math.min(scrollTop, from);
    last = performance.now();
    draw(last);          // сразу актуальный кадр — без задержки до следующего requestAnimationFrame
    raf = requestAnimationFrame(loop);
  }

  // Рисуем заранее — за экран до появления раздела, а уходя далеко, стираем холст. Иначе при резкой
  // прокрутке на мгновение виден последний кадр с прошлого раза (например, собранные стрелки).
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (entries) {
      visible = entries[0].isIntersecting;
      if (visible) start();
      else if (!reduced) clearCanvas();
    }, { rootMargin: '100% 0px 100% 0px' }).observe(section);
  } else {
    visible = true;
    start();
  }

  document.addEventListener('mr-prefs', function () {
    lookFrom = { c: col.slice(), normal: normal };
    lookTo = readLook();
    lookT0 = performance.now();
    if (visible) { if (reduced) draw(lookT0 + 400); else start(); }
  });

  layout();
  window.addEventListener('resize', layout);
  window.addEventListener('load', layout);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(layout);
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(layout).observe(section);
})();
