// «Стрежень» — вариант «Словарь форм». Частицы на WebGL без библиотек.
// Каждая форма что-то значит в продукте (словарь форм, docs/08-visual-concept.md):
//   край с Енисеем — «это про наш край»; облако тянется к полю — «система слушает»;
//   три облака VK, OK, MAX текут на карту — «идёт поиск»; города загораются — «найдено»;
//   вспышка и волны — «распространение»; точки гаснут — «пусто»; облако MAX серое — «сбой»;
//   сетка таблицы — «файл готов». Плюс местные образы: Коммунальный мост и часовня.
//
// Модель — N точек (x, y, z, код). Код = цвет палитры (0–7); +8 — точка «течёт»,
// а дробная часть — её место на пути (0…1): по пути бегут светлые импульсы.
// При прокрутке точки перелетают из модели одного раздела в модель следующего.

(function () {
  'use strict';

  var canvas = document.getElementById('gl');
  var reduced = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var gl = canvas.getContext('webgl', { antialias: false, alpha: false, depth: false, powerPreference: 'high-performance' });
  if (!gl) { canvas.style.display = 'none'; return; }

  var light = Math.min(screen.width, screen.height) < 700 || (window.matchMedia && window.matchMedia('(pointer: coarse)').matches);
  var N = light ? 9000 : 20000;
  var STARS = light ? 700 : 1400;

  /* ---------- Палитра ---------- */

  var BLUE = 0, WHITE = 1, GOLD = 2, VK = 3, OK = 4, MAX = 5, GREY = 6, DIM = 7;
  var PALETTE = [
    0.30, 0.55, 1.00, // синий
    0.93, 0.95, 1.00, // белый
    1.00, 0.70, 0.28, // золото
    0.22, 0.52, 1.00, // ВКонтакте
    1.00, 0.50, 0.20, // Одноклассники
    0.18, 0.86, 0.55, // MAX
    0.50, 0.53, 0.60, // серый: сбой площадки, мерцает
    0.36, 0.45, 0.62  // приглушённый: основа карты, погасшие точки
  ];
  /** Точка, которая «течёт»: f — место на пути от 0 до 1 */
  function flow(color, f) { return color + 8 + Math.max(0, Math.min(0.999, f)); }

  /* ---------- Случайные числа ---------- */

  function rng(seed) {
    var s = seed >>> 0;
    return function () {
      s = (s + 0x6D2B79F5) >>> 0;
      var t = s;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  var R = rng(20261019);
  function gauss() { var u = R() || 1e-6, v = R(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }
  function jit(a) { return (R() - 0.5) * a; }
  /** Синий, белый или золото по «тону» 0…1 с лёгким разбросом */
  function tone(t, v) {
    var x = t + (R() - 0.5) * (v === undefined ? 0.18 : v);
    return x < 0.34 ? BLUE : x < 0.67 ? WHITE : GOLD;
  }
  function pick(weights) { // индекс по весам
    var s = 0, i;
    for (i = 0; i < weights.length; i++) s += weights[i];
    var r = R() * s;
    for (i = 0; i < weights.length; i++) { r -= weights[i]; if (r <= 0) return i; }
    return weights.length - 1;
  }

  // Собирает модель из частей [вес, функция одной точки]
  function compose(parts) {
    var a = new Float32Array(N * 4), i = 0;
    var total = parts.reduce(function (s, p) { return s + p[0]; }, 0);
    function put(x, y, z, code) {
      if (i >= N) return;
      a[i * 4] = x; a[i * 4 + 1] = y; a[i * 4 + 2] = z; a[i * 4 + 3] = code;
      i++;
    }
    parts.forEach(function (p, k) {
      var n = k === parts.length - 1 ? N - i : Math.round(N * p[0] / total);
      for (var j = 0; j < n; j++) p[1](put);
    });
    return a;
  }

  /* ---------- География края ---------- */
  // Те же данные, что в мокапе (web/src/dots/krai-geo.ts): контур упрощён вручную,
  // реки и города — реальные координаты, проекция Ламберта.

  var OUTLINE = [[92.3,52.3],[93.2,51.8],[94.3,52.2],[95.6,52.6],[96.5,53.3],[97.4,54.0],[98.1,54.9],[97.6,55.6],[98.5,56.4],[100.0,57.3],[101.5,58.2],[102.2,59.4],[103.6,60.0],[105.6,60.4],[106.4,61.2],[107.5,62.0],[108.6,62.8],[108.5,64.0],[107.7,65.3],[109.2,66.3],[111.6,66.9],[112.8,68.3],[112.3,69.8],[113.2,71.2],[113.8,72.5],[112.0,73.9],[110.2,74.0],[108.0,73.4],[106.5,73.7],[107.5,74.9],[105.0,75.9],[104.3,77.7],[101.5,77.0],[98.0,76.3],[95.0,76.1],[92.0,75.8],[89.0,75.4],[87.0,74.9],[86.0,74.3],[86.8,73.8],[82.0,73.6],[80.4,73.4],[80.6,72.6],[82.3,71.9],[83.2,70.6],[83.4,69.5],[83.0,68.0],[83.6,66.8],[84.5,65.3],[85.2,63.8],[85.0,62.5],[84.6,61.4],[85.6,60.2],[87.0,59.3],[88.6,58.6],[89.3,57.6],[88.6,56.8],[89.2,56.0],[89.8,55.4],[89.3,54.8],[90.4,54.6],[91.4,53.9],[91.5,53.2],[91.0,52.7]];
  var SEVERNAYA = [[95.0,79.0],[97.5,78.3],[100.5,78.6],[104.5,79.4],[101.5,80.5],[97.0,81.1],[93.5,80.3]];
  var YENISEI = [[91.6,52.9],[91.7,53.6],[91.3,54.4],[91.5,55.2],[92.4,55.95],[92.87,56.01],[93.3,56.5],[92.9,57.3],[92.5,58.2],[92.2,58.5],[92.3,59.3],[91.6,60.2],[90.3,61.3],[89.5,62.4],[88.3,63.6],[87.9,64.8],[87.98,65.79],[86.8,66.6],[86.58,67.47],[86.4,68.4],[86.18,69.4],[85.0,70.2],[83.4,71.0],[82.0,71.8],[81.0,72.6]];
  var TRIBUTARIES = [
    [[101.6,58.1],[99.2,58.55],[97.45,58.38],[95.6,58.45],[94.0,58.3],[92.4,58.15]], // Ангара
    [[102.6,60.3],[100.4,60.7],[98.2,61.1],[96.37,61.67],[94.5,61.55],[92.3,61.5],[90.2,61.6]], // Подкаменная Тунгуска
    [[106.4,61.6],[104.6,62.6],[102.8,63.6],[100.22,64.27],[97.8,64.6],[95.2,64.9],[92.6,65.3],[90.3,65.7],[88.1,65.8]] // Нижняя Тунгуска
  ];
  var CITIES = {
    'Красноярск': [92.87, 56.01, 1], 'Норильск': [88.2, 69.35, 1], 'Ачинск': [90.5, 56.27, 1],
    'Канск': [95.7, 56.2, 1], 'Минусинск': [91.69, 53.71, 1], 'Лесосибирск': [92.48, 58.23, 0],
    'Енисейск': [92.17, 58.45, 0], 'Дудинка': [86.18, 69.4, 0], 'Железногорск': [93.53, 56.25, 0],
    'Зеленогорск': [94.59, 56.11, 0], 'Шарыпово': [89.18, 55.54, 0], 'Назарово': [90.4, 56.0, 0],
    'Кодинск': [99.18, 58.6, 0], 'Богучаны': [97.45, 58.38, 0], 'Туруханск': [87.98, 65.79, 0],
    'Игарка': [86.58, 67.47, 0], 'Тура': [100.22, 64.27, 0], 'Ванавара': [102.28, 60.34, 0],
    'Байкит': [96.37, 61.67, 0], 'Хатанга': [102.47, 71.98, 0], 'Диксон': [80.55, 73.51, 0]
  };
  // Найденные публикации по городам (демо). Точек-городов ровно столько, где регион известен.
  var FOUND = [['Красноярск', 6], ['Норильск', 4], ['Канск', 2], ['Ачинск', 1], ['Минусинск', 1], ['Лесосибирск', 1]];

  var RAD = Math.PI / 180, LON0 = 96 * RAD, LAT1 = 52 * RAD, LAT2 = 74 * RAD, LAT0 = 64 * RAD;
  function tanHalf(p) { return Math.tan(Math.PI / 4 + p / 2); }
  var NL = Math.log(Math.cos(LAT1) / Math.cos(LAT2)) / Math.log(tanHalf(LAT2) / tanHalf(LAT1));
  var FL = Math.cos(LAT1) * Math.pow(tanHalf(LAT1), NL) / NL;
  var RHO0 = FL / Math.pow(tanHalf(LAT0), NL);
  function lambert(p) {
    var rho = FL / Math.pow(tanHalf(p[1] * RAD), NL), th = NL * (p[0] * RAD - LON0);
    return [rho * Math.sin(th) / RAD, (RHO0 - rho * Math.cos(th)) / RAD]; // y вверх
  }
  // Нормируем: край высотой MAP_H по центру начала координат
  var MAP_H = 2.5;
  var GEO = (function () {
    var all = OUTLINE.concat(SEVERNAYA).map(lambert);
    var x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    all.forEach(function (p) { x0 = Math.min(x0, p[0]); x1 = Math.max(x1, p[0]); y0 = Math.min(y0, p[1]); y1 = Math.max(y1, p[1]); });
    var s = MAP_H / (y1 - y0), cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    function norm(p) { var q = lambert(p); return [(q[0] - cx) * s, (q[1] - cy) * s]; }
    var cities = {};
    Object.keys(CITIES).forEach(function (k) { var c = CITIES[k]; cities[k] = { p: norm(c), major: c[2] === 1 }; });
    return {
      outline: polyline(OUTLINE.map(norm), true),
      islands: polyline(SEVERNAYA.map(norm), true),
      yenisei: polyline(YENISEI.map(norm), false),
      tribs: TRIBUTARIES.map(function (t) { return polyline(t.map(norm), false); }),
      cities: cities,
      bbox: [(x0 - cx) * s, (x1 - cx) * s, (y0 - cy) * s, (y1 - cy) * s]
    };
  })();

  // Ломаная с равномерной выборкой по длине
  function polyline(pts, closed) {
    var p = closed ? pts.concat([pts[0]]) : pts, cum = [0];
    for (var i = 1; i < p.length; i++) cum.push(cum[i - 1] + Math.hypot(p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1]));
    var total = cum[cum.length - 1];
    return {
      pts: pts,
      total: total,
      at: function (u) { // точка на доле пути u
        var d = u * total, k = 1;
        while (k < cum.length - 1 && cum[k] < d) k++;
        var t = (d - cum[k - 1]) / Math.max(1e-9, cum[k] - cum[k - 1]);
        return [p[k - 1][0] + (p[k][0] - p[k - 1][0]) * t, p[k - 1][1] + (p[k][1] - p[k - 1][1]) * t];
      }
    };
  }
  function inside(x, y, poly) {
    var inn = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      var a = poly[i], b = poly[j];
      if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) inn = !inn;
    }
    return inn;
  }
  // Лёгкий рельеф: карта не плоская, а чуть «дышит» по глубине
  function relief(x, y) { return 0.05 * Math.sin(x * 6 + 1) * Math.cos(y * 4) + jit(0.05); }

  /**
   * Части карты края. o: ox, oy, s — сдвиг и масштаб карты внутри модели;
   * веса частей и цвета; river — течёт ли Енисей.
   */
  function mapParts(o) {
    var s = o.s || 1, ox = o.ox || 0, oy = o.oy || 0;
    function T(p, z) { return [ox + p[0] * s, oy + p[1] * s, (z || 0) * s]; }
    function put3(put, p, z, code) { var q = T(p, z); put(q[0], q[1], q[2], code); }
    var parts = [];
    if (o.outline) parts.push([o.outline, function (put) {
      var line = R() < 0.92 ? GEO.outline : GEO.islands, p = line.at(R());
      put3(put, [p[0] + jit(0.012), p[1] + jit(0.012)], jit(0.04), o.outlineColor());
    }]);
    if (o.fill) parts.push([o.fill, function (put) {
      var b = GEO.bbox;
      for (var i = 0; i < 60; i++) {
        var x = b[0] + R() * (b[1] - b[0]), y = b[2] + R() * (b[3] - b[2]);
        if (inside(x, y, GEO.outline.pts) || inside(x, y, GEO.islands.pts)) { put3(put, [x, y], relief(x, y), o.fillColor()); return; }
      }
      put3(put, GEO.outline.at(R()), 0, o.fillColor());
    }]);
    if (o.river) parts.push([o.river, function (put) {
      var u = R(), p = GEO.yenisei.at(u); // Енисей течёт с юга на север
      put3(put, [p[0] + jit(0.022), p[1] + jit(0.022)], jit(0.03), o.riverFlow ? flow(BLUE, u) : o.riverColor);
    }]);
    if (o.tribs) parts.push([o.tribs, function (put) {
      var k = pick(GEO.tribs.map(function (t) { return t.total; })), u = R(), p = GEO.tribs[k].at(u);
      put3(put, [p[0] + jit(0.016), p[1] + jit(0.016)], jit(0.03), o.riverFlow ? flow(BLUE, u) : o.riverColor);
    }]);
    if (o.cities) parts.push([o.cities, function (put) {
      var names = Object.keys(GEO.cities);
      var k = pick(names.map(function (n) { return GEO.cities[n].major ? 3 : 1; }));
      var c = GEO.cities[names[k]], r = c.major ? 0.026 : 0.013;
      put3(put, [c.p[0] + gauss() * r, c.p[1] + gauss() * r], gauss() * r, names[k] === 'Красноярск' ? GOLD : WHITE);
    }]);
    return parts;
  }

  /* ---------- Формы словаря ---------- */

  // Лендинг, покой: силуэт края с юга до Таймыра, по нему течёт Енисей
  function krai() {
    return compose(mapParts({
      outline: 0.2, outlineColor: function () { return R() < 0.65 ? BLUE : WHITE; },
      fill: 0.36, fillColor: function () { return R() < 0.55 ? DIM : BLUE; },
      river: 0.2, tribs: 0.09, riverFlow: true,
      cities: 0.07
    }).concat([[0.08, function (put) { // редкая пыль вокруг карты
      // Гуще у силуэта и мягко сходит на нет с расстоянием: без прямоугольной границы
      // (раньше пыль заполняла прямоугольник вокруг карты, и он читался как подложка)
      var p = (R() < 0.92 ? GEO.outline : GEO.islands).at(R());
      var a = R() * Math.PI * 2, r = 0.02 - Math.log(1 - R() * 0.997) * 0.13;
      put(p[0] + Math.cos(a) * r, p[1] + Math.sin(a) * r, jit(0.8), R() < 0.7 ? DIM : BLUE);
    }]]));
  }

  // Человек вводит запрос: облако оживает и тянется к полю ввода (вправо)
  function listening() {
    return compose([
      [0.5, function (put) { // облако
        var r = Math.pow(R(), 0.5);
        put(-0.35 + gauss() * 0.36 * r, gauss() * 0.3 * r, gauss() * 0.32 * r, pick([45, 35, 20]));
      }],
      [0.38, function (put) { // хвост к полю ввода
        var u = Math.pow(R(), 0.8), w = 0.2 * (1 - u) + 0.02;
        put(-0.15 + u * 2.05 + jit(0.04), 0.1 * Math.sin(u * 3.2) - 0.06 * u + gauss() * w * 0.5, gauss() * w * 0.5, flow(R() < 0.6 ? BLUE : WHITE, u));
      }],
      [0.12, function (put) { // искры вокруг
        var a = R() * Math.PI * 2, r = 0.55 + R() * 0.5;
        put(-0.35 + Math.cos(a) * r, Math.sin(a) * r * 0.8, jit(0.6), R() < 0.5 ? DIM : BLUE);
      }]
    ]);
  }

  // Идёт поиск: три облака VK, OK, MAX, из них точки текут на карту.
  // failed — площадка со сбоем: её облако серое и мерцает, поток не идёт.
  var CLOUDS = [[VK, -1.05, 0.72], [OK, -1.28, 0.0], [MAX, -1.05, -0.72]];
  var TARGETS = ['Красноярск', 'Норильск', 'Канск', 'Ачинск', 'Лесосибирск', 'Минусинск'];
  function clouds(failed) {
    var MS = 0.72, MX = 0.82;
    var map = mapParts({
      s: MS, ox: MX,
      outline: 0.12, outlineColor: function () { return R() < 0.5 ? BLUE : DIM; },
      fill: 0.17, fillColor: function () { return DIM; },
      river: 0.05, riverFlow: true
    });
    return compose(map.concat([
      [0.3, function (put) { // облака площадок
        var c = CLOUDS[Math.floor(R() * 3)], bad = c[0] === failed, r = Math.pow(R(), 0.6) * (bad ? 1.25 : 1);
        put(c[1] + gauss() * 0.17 * r, c[2] + gauss() * 0.15 * r, gauss() * 0.16 * r, bad ? GREY : c[0]);
      }],
      [0.36, function (put) { // потоки к городам на карте
        var c = CLOUDS[Math.floor(R() * 3)];
        if (c[0] === failed) { // у площадки со сбоем потока нет — точки остаются в облаке
          put(c[1] + gauss() * 0.22, c[2] + gauss() * 0.2, gauss() * 0.2, GREY);
          return;
        }
        var t = GEO.cities[TARGETS[Math.floor(R() * TARGETS.length)]].p;
        var ex = MX + t[0] * MS, ey = t[1] * MS, u = R();
        var cx = (c[1] + ex) / 2, cy = (c[2] + ey) / 2 + 0.35; // дуга
        var x = (1 - u) * (1 - u) * c[1] + 2 * (1 - u) * u * cx + u * u * ex;
        var y = (1 - u) * (1 - u) * c[2] + 2 * (1 - u) * u * cy + u * u * ey;
        var w = 0.035 * (1 - u) + 0.006;
        put(x + jit(w), y + jit(w), jit(w) + Math.sin(u * Math.PI) * 0.12, flow(c[0], u));
      }]
    ]));
  }

  // Найдено: на карте загораются города, где вышли публикации
  function found() {
    return compose(mapParts({
      outline: 0.15, outlineColor: function () { return R() < 0.5 ? BLUE : DIM; },
      fill: 0.3, fillColor: function () { return DIM; },
      river: 0.08, tribs: 0.03, riverColor: DIM
    }).concat([
      [0.3, function (put) { // золотые скопления: больше публикаций — крупнее
        var f = FOUND[pick(FOUND.map(function (x) { return x[1]; }))], c = GEO.cities[f[0]].p;
        var r = 0.016 + 0.01 * Math.sqrt(f[1]);
        put(c[0] + gauss() * r, c[1] + gauss() * r, gauss() * r, GOLD);
      }],
      [0.14, function (put) { // кольца вокруг найденного — расходятся от города
        var f = FOUND[pick(FOUND.map(function (x) { return Math.sqrt(x[1]); }))], c = GEO.cities[f[0]].p;
        var r0 = 0.04 + 0.025 * Math.sqrt(f[1]), u = R(), a = R() * Math.PI * 2, r = r0 + u * 0.12;
        put(c[0] + Math.cos(a) * r, c[1] + Math.sin(a) * r, 0, flow(GOLD, u));
      }],
      [0.08, function (put) { // остальные города — тихо
        var names = Object.keys(GEO.cities), c = GEO.cities[names[Math.floor(R() * names.length)]].p;
        put(c[0] + gauss() * 0.01, c[1] + gauss() * 0.01, 0, DIM);
      }]
    ]));
  }

  // «Распространение»: вспышка из точки-источника и волны к перепечаткам
  function spread() {
    var SX = 0.1, PY = -0.3, TILT = 0.5, STEP = 0.28; // источник почти в центре: волны не заходят под текст
    var ct = Math.cos(TILT), st = Math.sin(TILT);
    function rot(x, y, z) { return [x, ct * y - st * z, st * y + ct * z]; } // наклон плоскости к зрителю
    var nodes = [], i;
    var plats = [VK, VK, VK, VK, VK, VK, VK, VK, VK, OK, OK, OK, OK, MAX, MAX]; // 15 размещений: 9 / 4 / 2
    for (i = 0; i < plats.length; i++) {
      var ring = 1 + (i % 5), a = (i * 2.399) % (Math.PI * 2);
      nodes.push({ x: SX + Math.cos(a) * ring * STEP, z: Math.sin(a) * ring * STEP, h: 0.12 + (i % 4) * 0.07, c: plats[i] });
    }
    return compose([
      [0.06, function (put) { var p = rot(SX + gauss() * 0.04, PY + 0.02 + Math.abs(gauss()) * 0.04, gauss() * 0.04); put(p[0], p[1], p[2], GOLD); }],
      [0.2, function (put) { // вспышка: лучи от источника вверх и в стороны
        var z = R(), ph = R() * Math.PI * 2, s = Math.sqrt(1 - z * z), l = Math.pow(R(), 1.8) * 0.85;
        var p = rot(SX + s * Math.cos(ph) * l, PY + z * l, s * Math.sin(ph) * l);
        put(p[0], p[1], p[2], flow(GOLD, l / 0.85));
      }],
      [0.34, function (put) { // волны по «земле»
        var k = 1 + Math.floor(R() * 5), r = k * STEP + jit(0.03), a = R() * Math.PI * 2;
        var p = rot(SX + Math.cos(a) * r, PY, Math.sin(a) * r);
        put(p[0], p[1], p[2], flow(R() < 0.75 ? BLUE : WHITE, r / (5.5 * STEP)));
      }],
      [0.24, function (put) { // перепечатки: точки цвета площадки на ножках
        var n = nodes[Math.floor(R() * nodes.length)], p;
        if (R() < 0.35) p = rot(n.x + jit(0.006), PY + R() * n.h, n.z + jit(0.006));
        else p = rot(n.x + gauss() * 0.025, PY + n.h + gauss() * 0.025, n.z + gauss() * 0.025);
        put(p[0], p[1], p[2], n.c);
      }],
      [0.16, function (put) { // дуги от источника к перепечаткам
        var n = nodes[Math.floor(R() * nodes.length)], u = R();
        var x = SX + (n.x - SX) * u, z = n.z * u, y = PY + Math.sin(u * Math.PI) * 0.35 + n.h * u;
        var p = rot(x + jit(0.01), y + jit(0.01), z + jit(0.01));
        put(p[0], p[1], p[2], flow(WHITE, u));
      }]
    ]);
  }

  // Выгрузка XLSX: точки складываются в сетку таблицы
  function grid() {
    var W = 1.05, H = 0.72, ROWS = 7, COLS = 5;
    var colX = [-W, -0.78, -0.2, 0.3, 0.72, W]; // № · площадка · заголовок · дата · ссылка
    function rowY(k) { return H - k * (2 * H / ROWS); }
    var cells = [];
    for (var r = 1; r < ROWS; r++) for (var c = 0; c < COLS; c++) cells.push([r, c, 0.35 + R() * 0.55]);
    return compose([
      [0.32, function (put) { // линии сетки
        if (R() < 0.55) { var k = Math.floor(R() * (ROWS + 1)); put(-W + R() * 2 * W, rowY(k) + jit(0.006), jit(0.02), R() < 0.6 ? BLUE : WHITE); }
        else { var x = colX[Math.floor(R() * colX.length)]; put(x + jit(0.006), -H + R() * 2 * H, jit(0.02), R() < 0.6 ? BLUE : WHITE); }
      }],
      [0.16, function (put) { // строка заголовков — золотом
        put(-W + R() * 2 * W, rowY(0) - R() * (2 * H / ROWS), jit(0.02), GOLD);
      }],
      [0.4, function (put) { // данные в ячейках
        var cell = cells[Math.floor(R() * cells.length)], x0 = colX[cell[1]] + 0.04, x1 = colX[cell[1] + 1] - 0.04;
        var y = (rowY(cell[0]) + rowY(cell[0] + 1)) / 2;
        put(x0 + R() * (x1 - x0) * cell[2], y + jit(0.03), jit(0.02), cell[1] === COLS - 1 ? BLUE : WHITE);
      }],
      [0.12, function (put) { // искры вокруг: файл «собирается»
        var a = R() * Math.PI * 2, r = 1.3 + R() * 0.6;
        put(Math.cos(a) * r, Math.sin(a) * r * 0.7, jit(0.8), R() < 0.5 ? DIM : GOLD);
      }]
    ]);
  }

  // Пусто: точки спокойно рассеиваются и гаснут
  function empty() {
    return compose([[1, function (put) {
      put((R() - 0.5) * 8, (R() - 0.5) * 5, -2.4 + R() * 3.2, R() < 0.88 ? DIM : BLUE);
    }]]);
  }

  // Пыль — модели нет, частицы рассеяны по всему пространству
  function dust() {
    return compose([[1, function (put) {
      put((R() - 0.5) * 7.5, (R() - 0.5) * 4.6, -2.4 + R() * 3.4, pick([40, 35, 25]));
    }]]);
  }

  // Местный образ: Коммунальный мост через Енисей — тот, что на десятирублёвой купюре.
  // Модель — один «период» моста: семь пролётов от −2.2 до 2.2, без правой опоры и с водой
  // ровно в этих границах. Во всю ширину окна мост собирается из повторов периода
  // (bridgeCopies и проходы с uShift в кадре) — пролёты те же, густота точек та же.
  var BRIDGE_PERIOD = 4.4;
  function bridge() {
    var DECK = 0.28, WATER = -0.55, SPRING = WATER + 0.16, CROWN = DECK - 0.05, Z = 0.12;
    var PIERS = [-2.2, -1.62, -1.06, -0.36, 0.36, 1.06, 1.62, 2.2];
    function span() { var k = Math.floor(R() * (PIERS.length - 1)); return [PIERS[k], PIERS[k + 1]]; }
    function archY(t) { return SPRING + (CROWN - SPRING) * (1 - t * t); }
    return compose([
      [0.22, function (put) { put(-2.2 + R() * 4.4, DECK + jit(0.012), jit(2 * Z), R() < 0.7 ? WHITE : BLUE); }],
      [0.07, function (put) { // перила и столбики
        var z = R() < 0.5 ? -Z : Z;
        if (R() < 0.7) put(-2.2 + R() * 4.4, DECK + 0.07, z, WHITE);
        else { var x = -2.2 + Math.floor(R() * 55) * 0.08; put(x, DECK + R() * 0.07, z, WHITE); }
      }],
      [0.24, function (put) { // арки
        var s = span(), t = R() * 2 - 1, w = s[1] - s[0];
        put(s[0] + w * (t + 1) / 2 + jit(0.008), archY(t) + jit(0.012), (R() < 0.5 ? -Z : Z) * 0.85 + jit(0.01), GOLD);
      }],
      [0.12, function (put) { // стойки между аркой и настилом
        var s = span(), w = s[1] - s[0], t = Math.round((R() * 2 - 1) * 6) / 6, y0 = archY(t);
        put(s[0] + w * (t + 1) / 2 + jit(0.006), y0 + R() * (DECK - y0), (R() < 0.5 ? -Z : Z) * 0.85, BLUE);
      }],
      [0.08, function (put) { // опоры (правая — это левая опора следующего повтора)
        var x = PIERS[Math.floor(R() * (PIERS.length - 1))];
        put(x + jit(0.06), WATER + R() * (SPRING + 0.04 - WATER), jit(2 * Z), WHITE);
      }],
      [0.178, function (put) { // Енисей под мостом течёт (густота воды — прежняя: 0.21 на 5.2 единицы)
        var x = -2.2 + R() * 4.4, z = -0.7 + R() * 1.2;
        // четыре импульса на период: на стыках повторов течение не прерывается
        put(x, WATER + 0.02 * Math.sin(x * 6 + z * 4) + jit(0.01), z, flow(R() < 0.8 ? BLUE : WHITE, (x + 2.2) / 5.5));
      }],
      [0.06, function (put) { // фонари: 15 на период, шаг почти прежний (0.293 вместо 0.3)
        var x = -2.2 + (Math.floor(R() * 15) + 0.5) * (4.4 / 15);
        put(x + gauss() * 0.012, DECK + 0.2 + gauss() * 0.012, (R() < 0.5 ? -Z : Z) + gauss() * 0.012, GOLD);
      }]
    ]);
  }

  // Местный образ: часовня Параскевы Пятницы — восьмерик с окнами, шатёр, луковица, крест
  function chapel() {
    var Y = -0.1;
    function octV(r, k) { var a = k * Math.PI / 4 + Math.PI / 8; return [r * Math.cos(a), r * Math.sin(a)]; }
    function octPt(r, u) {
      var k = Math.floor(u) % 8, f = u - Math.floor(u);
      var A = octV(r, k), B = octV(r, k + 1);
      return [A[0] + (B[0] - A[0]) * f, A[1] + (B[1] - A[1]) * f, k, f];
    }
    var FACE = 2 * 0.42 * Math.sin(Math.PI / 8);
    var WW = 0.05, WTOP = -0.36, WBOT = -0.68;
    function inWindow(k, f, y) {
      if (k % 2 === 0) return false;
      var dx = (f - 0.5) * FACE;
      if (Math.abs(dx) > WW) return false;
      if (y > WBOT && y < WTOP) return true;
      var dy = y - WTOP;
      return dy >= 0 && dx * dx + dy * dy < WW * WW;
    }
    return compose([
      [0.07, function (put) { // цоколь
        var p, y;
        if (R() < 0.3) { p = octPt(0.42 + R() * 0.08, R() * 8); y = -0.88; }
        else { p = octPt(0.5, R() * 8); y = -1.0 + R() * 0.12; }
        put(p[0], y + Y, p[1], tone(0.35));
      }],
      [0.30, function (put) { // стены
        for (var i = 0; i < 30; i++) {
          var y = -0.88 + R() * 0.76, p = octPt(0.42, R() * 8);
          if (!inWindow(p[2], p[3], y)) { put(p[0], y + Y, p[1], tone(0.55)); return; }
        }
        put(0, -0.5 + Y, 0, WHITE);
      }],
      [0.06, function (put) { // наличники
        var k = 1 + 2 * Math.floor(R() * 4), s = R() * 4, dx, y;
        if (s < 1) { dx = -WW; y = WBOT + (WTOP - WBOT) * s; }
        else if (s < 2) { dx = WW; y = WBOT + (WTOP - WBOT) * (s - 1); }
        else if (s < 2.6) { dx = -WW + 2 * WW * (s - 2) / 0.6; y = WBOT; }
        else { var a = Math.PI * (s - 2.6) / 1.4; dx = WW * Math.cos(a); y = WTOP + WW * Math.sin(a); }
        var p = octPt(0.425, k + 0.5 + dx / FACE);
        put(p[0], y + Y, p[1], tone(0.95, 0.1));
      }],
      [0.04, function (put) { // рёбра стен
        var v = octV(0.425, Math.floor(R() * 8));
        put(v[0] + jit(0.01), -0.88 + R() * 0.76 + Y, v[1] + jit(0.01), tone(0.15));
      }],
      [0.04, function (put) { // карниз
        var p = octPt(0.47 + R() * 0.02, R() * 8);
        put(p[0], -0.12 + R() * 0.06 + Y, p[1], tone(0.75));
      }],
      [0.24, function (put) { // шатёр: равномерно по площади
        var t;
        do { t = R(); } while (R() > 1 - t * 0.79);
        var p = octPt(0.48 * (1 - t) + 0.1 * t, R() * 8);
        put(p[0], -0.06 + t * 0.58 + Y, p[1], tone(0.2 + t * 0.25));
      }],
      [0.04, function (put) { // рёбра шатра
        var k = Math.floor(R() * 8), t = R(), a = octV(0.48, k), b = octV(0.1, k);
        put(a[0] + (b[0] - a[0]) * t, -0.06 + t * 0.58 + Y, a[1] + (b[1] - a[1]) * t, tone(0.7));
      }],
      [0.03, function (put) { // барабан
        var a = R() * Math.PI * 2;
        put(0.1 * Math.cos(a), 0.52 + R() * 0.12 + Y, 0.1 * Math.sin(a), tone(0.5));
      }],
      [0.12, function (put) { // луковица
        var t = R(), r = 0.19 * Math.sin(Math.PI * Math.pow(0.15 + 0.85 * t, 0.8)), a = R() * Math.PI * 2;
        put(r * Math.cos(a), 0.64 + t * 0.36 + Y, r * Math.sin(a), tone(0.95, 0.1));
      }],
      [0.035, function (put) { // крест
        var s = R(), x, y;
        if (s < 0.55) { x = 0; y = 1.0 + R() * 0.34; }
        else if (s < 0.85) { x = -0.08 + R() * 0.16; y = 1.25; }
        else { x = -0.05 + R() * 0.1; y = 1.13 + x * 0.35; }
        put(x + jit(0.008), y + Y, jit(0.008), GOLD);
      }],
      [0.035, function (put) { // площадка вокруг
        var a = R() * Math.PI * 2, r = 0.6 + R() * 0.3;
        put(r * Math.cos(a), -1.0 + Y, r * Math.sin(a), tone(0.1));
      }]
    ]);
  }

  // Параметры форм: вращение (spin — по кругу, иначе покачивание), масштаб, сдвиги.
  // model: false — облако без формы; wide — во всю ширину (мост).
  // listening.tail — откуда течёт поток (центр облака) и где кончается хвост в модели:
  // по ним хвост изгибается к полю ввода (data-flow-target).
  var META = {
    krai: { build: krai, model: true, base: 0, amp: 0.32, scale: 1.0 },
    bridge: { build: bridge, model: true, wide: true, width: 5.2, period: BRIDGE_PERIOD, base: -0.14, amp: 0.12, scale: 1.0 },
    listening: { build: listening, model: true, base: 0.1, amp: 0.2, scale: 1.0, tail: { src: [-0.35, 0, 0], end: [1.9, -0.066, 0] } },
    searching: { build: function () { return clouds(null); }, model: true, base: -0.15, amp: 0.16, scale: 0.85 },
    found: { build: found, model: true, base: 0.12, amp: 0.25, scale: 1.0 },
    spread: { build: spread, model: true, base: 0.35, amp: 0.3, scale: 0.92, shift: 0.06 },
    grid: { build: grid, model: true, base: -0.38, amp: 0.18, scale: 0.9 },
    empty: { build: empty, model: false, spin: true, base: 0, scale: 1.0 },
    failure: { build: function () { return clouds(MAX); }, model: true, base: 0.15, amp: 0.16, scale: 0.85 },
    dust: { build: dust, model: false, spin: true, base: 0, scale: 1.0 },
    // в финале — справа от огромной надписи, над колонками подвала
    chapel: { build: chapel, model: true, spin: true, base: 0.5, scale: 0.74, lift: 0.42, shift: 0.06 }
  };

  /* ---------- Шейдеры ---------- */

  var VS = [
    'attribute vec4 aFrom;',
    'attribute vec4 aTo;',
    'attribute vec4 aRnd;',
    'uniform float uP, uTime, uSpread, uIntro, uAspect, uPx, uTilt, uAlpha;',
    'uniform vec4 uA;',
    'uniform vec4 uB;',
    'uniform vec2 uMouse;',
    'uniform vec3 uPal[8];',
    // «Система слушает»: на сколько сдвинуть конец потока, чтобы он упёрся в поле ввода
    // (xy — в координатах экрана; z = 1 — у формы есть поток к полю; у остальных форм — 0)
    'uniform vec3 uTgtA;',
    'uniform vec3 uTgtB;',
    // Над колонкой текста выше поля поток невидим (узкий экран: поток идёт сверху сквозь
    // заголовок) — прямоугольник x0, y0, x1, y1 на экране и мягкость его краёв
    'uniform vec4 uHide;',
    'uniform vec2 uHideSoft;',
    // Повтор формы во всю ширину (мост): сдвиг модели «откуда» (x) и «куда» (y) на целое число
    // периодов; uFade — повтор принадлежит форме «откуда» (x = 1) или «куда» (y = 1):
    // он проявляется вместе с ней и не удваивает точки соседней формы
    'uniform vec2 uShift;',
    'uniform vec2 uFade;',
    'varying vec3 vCol;',
    'varying float vAlpha;',
    'vec3 rotY(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(c * p.x + s * p.z, p.y, -s * p.x + c * p.z); }',
    'vec3 rotX(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(p.x, c * p.y - s * p.z, s * p.y + c * p.z); }',
    // Место текущей точки на пути (0…1); у точек, которые не текут, — 0
    'float along(float code) { float idx = floor(code + 0.0001); return step(7.5, idx) * (code - idx); }',
    // Цвет и яркость точки по коду: палитра, «течение» импульсами, мерцание сбоя, приглушённые точки
    'vec4 look(float code, float d) {',
    '  float idx = floor(code + 0.0001);',
    '  float f = code - idx;',
    '  float flowing = step(7.5, idx);',
    '  idx -= 8.0 * flowing;',
    '  vec3 c = uPal[int(idx)];',
    '  float a = 1.0;',
    '  if (flowing > 0.5) { float w = fract(f * 5.0 - uTime * 0.42); a = 0.22 + 0.78 * pow(w, 6.0); }',
    '  if (idx > 5.5 && idx < 6.5) a *= 0.3 + 0.7 * step(0.45, fract(sin(floor(uTime * 7.0) * 12.9898 + d * 78.233) * 43758.5453));',
    '  if (idx > 6.5) a *= 0.5;',
    '  return vec4(c, a);',
    '}',
    'void main() {',
    '  float d = aRnd.w;',
    '  float t = clamp((uP - d * 0.3) / 0.7, 0.0, 1.0);',
    '  float e = t * t * (3.0 - 2.0 * t);',
    '  vec3 a = rotY((aFrom.xyz + vec3(uShift.x, 0.0, 0.0)) * uA.z, uA.w); a.xy += uA.xy;',
    '  vec3 b = rotY((aTo.xyz + vec3(uShift.y, 0.0, 0.0)) * uB.z, uB.w); b.xy += uB.xy;',
    '  vec3 p = mix(a, b, e) + aRnd.xyz * uSpread * sin(3.14159 * e);',
    '  p += 0.01 * vec3(sin(uTime * 1.3 + d * 40.0), cos(uTime * 1.1 + d * 31.0), sin(uTime * 0.9 + d * 17.0));',
    '  p += aRnd.xyz * 4.0 * uIntro * (0.6 + d);',
    '  p = rotX(p, uTilt);',
    '  float z = 3.4 - min(p.z, 2.2);',
    '  vec2 q = vec2(p.x / uAspect, p.y) * (2.2 / z);',
    // поток изгибается к полю ввода: начало остаётся у облака, конец упирается в поле
    '  q += mix(along(aFrom.w) * uTgtA.xy, along(aTo.w) * uTgtB.xy, e);',
    // точка потока над текстом — гаснет, у поля ввода проявляется снова
    '  float tail = mix(step(0.0005, along(aFrom.w)) * uTgtA.z, step(0.0005, along(aTo.w)) * uTgtB.z, e);',
    '  float hx = smoothstep(uHide.x - uHideSoft.x, uHide.x + uHideSoft.x, q.x) * (1.0 - smoothstep(uHide.z - uHideSoft.x, uHide.z + uHideSoft.x, q.x));',
    '  float hy = smoothstep(uHide.y - uHideSoft.y, uHide.y + uHideSoft.y, q.y) * (1.0 - smoothstep(uHide.w - uHideSoft.y, uHide.w + uHideSoft.y, q.y));',
    '  float shown = 1.0 - tail * hx * hy;',
    '  vec2 dm = (q - uMouse) * vec2(uAspect, 1.0);',
    '  float dl = length(dm);',
    '  q += dm / (dl + 1e-4) * 0.05 * smoothstep(0.28, 0.0, dl) * vec2(1.0 / uAspect, 1.0);',
    '  gl_Position = vec4(q, 0.0, 1.0);',
    '  gl_PointSize = min(uPx * (3.4 / z) * (0.55 + d * 0.9), 26.0);',
    '  vec4 la = look(aFrom.w, d), lb = look(aTo.w, d);',
    '  vec3 col = mix(la.rgb, lb.rgb, e);',
    '  if (d > 0.965) col = mix(col, vec3(0.93, 0.95, 1.0), 0.7);',
    '  vCol = col;',
    '  vAlpha = uAlpha * mix(la.a, lb.a, e) * clamp(1.7 - z * 0.27, 0.25, 1.0) * (1.0 - uIntro * 0.5);',
    '  vAlpha *= mix(1.0, 1.0 - e, uFade.x) * mix(1.0, e, uFade.y) * shown;',
    '}'
  ].join('\n');

  var VS_STARS = [
    'attribute vec4 aS;',
    'uniform float uScroll, uTime, uPx, uAlpha;',
    'varying vec3 vCol;',
    'varying float vAlpha;',
    'void main() {',
    '  float y = fract(aS.y + uScroll * (0.00004 + aS.z * 0.00016));',
    '  gl_Position = vec4(aS.x * 2.0 - 1.0, y * 2.0 - 1.0, 0.0, 1.0);',
    '  gl_PointSize = uPx * (0.7 + aS.z * 1.4);',
    '  float tw = 0.55 + 0.45 * sin(uTime * (0.8 + aS.w * 2.5) + aS.w * 50.0);',
    '  vAlpha = uAlpha * (0.25 + 0.6 * aS.z) * tw;',
    '  vCol = aS.w < 0.12 ? vec3(0.45, 0.65, 1.0) : (aS.w < 0.22 ? vec3(1.0, 0.76, 0.38) : vec3(0.92, 0.94, 1.0));',
    '}'
  ].join('\n');

  var FS = [
    'precision mediump float;',
    'varying vec3 vCol;',
    'varying float vAlpha;',
    'void main() {',
    '  vec2 c = gl_PointCoord - 0.5;',
    '  float r = dot(c, c) * 4.0;',
    '  if (r > 1.0) discard;',
    '  gl_FragColor = vec4(vCol, exp(-r * 3.2) * vAlpha);',
    '}'
  ].join('\n');

  function program(vs, fs) {
    function sh(type, src) {
      var s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      return s;
    }
    var p = gl.createProgram();
    gl.attachShader(p, sh(gl.VERTEX_SHADER, vs));
    gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    var u = {}, n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (var i = 0; i < n; i++) {
      var info = gl.getActiveUniform(p, i);
      u[info.name.replace('[0]', '')] = gl.getUniformLocation(p, info.name);
    }
    return { p: p, u: u };
  }

  var P, S;
  try {
    P = program(VS, FS);
    S = program(VS_STARS, FS);
  } catch (err) {
    console.error(err);
    canvas.style.display = 'none';
    return;
  }

  function buffer(data) {
    var b = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    return b;
  }

  /* ---------- Размер окна ---------- */
  // Холст — во всё окно без полосы прокрутки (width: 100%), буфер — ровно такого же размера:
  // раньше он считался по innerWidth (с полосой прокрутки) и картинка чуть сжималась по ширине.
  // Размеры читаются только при изменении окна, в кадре раскладка не трогается.

  var W = 1, H = 1, dpr = 1;
  function readSize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = canvas.clientWidth || window.innerWidth;
    H = canvas.clientHeight || window.innerHeight;
  }

  // Мост — во всю ширину окна: сколько повторов периода нужно слева и справа, чтобы настил
  // доходил до краёв при любом развороте моста — своём (base ± amp) и за мышью. Дальний
  // край уходит вглубь и сужается в перспективе, поэтому ему обычно нужно больше повторов.
  var MOUSE_YAW = 0.25; // поворот формы за мышью, как в xf
  var copies = { l: 1, r: 1 };
  function bridgeCopies() {
    var m = META.bridge, asp = W / H, hw = asp * 3.4 / 2.2, G = 1.06; // G — запас за край окна
    var s = m.scale * Math.min(1, hw * 1.9 / m.width);
    // половина длины моста (в единицах модели) до края, который уходит вглубь; sn — синус разворота
    function need(sn) {
      var d = 2.2 * Math.sqrt(1 - sn * sn) - G * asp * sn;
      return d > 0.3 ? Math.min(16, 3.4 * G * asp / d / s) : 16;
    }
    var aMin = m.base - m.amp - MOUSE_YAW, aMax = m.base + m.amp + MOUSE_YAW;
    copies.l = Math.max(1, Math.ceil((need(-Math.sin(aMin)) - 2.2) / m.period));
    copies.r = Math.max(1, Math.ceil((need(Math.sin(aMax)) - 2.2) / m.period));
  }

  readSize();

  var bufs = {};
  Object.keys(META).forEach(function (k) { bufs[k] = buffer(META[k].build()); });

  var rnd = new Float32Array(N * 4);
  for (var i = 0; i < N; i++) {
    var z = 2 * R() - 1, ph = 2 * Math.PI * R(), s = Math.sqrt(1 - z * z), m = 0.4 + R() * 0.9;
    rnd[i * 4] = s * Math.cos(ph) * m; rnd[i * 4 + 1] = s * Math.sin(ph) * m; rnd[i * 4 + 2] = z * m; rnd[i * 4 + 3] = R();
  }
  var rndBuf = buffer(rnd);

  var stars = new Float32Array(STARS * 4);
  for (var j = 0; j < STARS; j++) {
    stars[j * 4] = R(); stars[j * 4 + 1] = R(); stars[j * 4 + 2] = Math.pow(R(), 2.2); stars[j * 4 + 3] = R();
  }
  var starBuf = buffer(stars);

  var locFrom = gl.getAttribLocation(P.p, 'aFrom');
  var locTo = gl.getAttribLocation(P.p, 'aTo');
  var locRnd = gl.getAttribLocation(P.p, 'aRnd');
  var locS = gl.getAttribLocation(S.p, 'aS');

  function attr(loc, buf) {
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 4, gl.FLOAT, false, 0, 0);
  }

  /* ---------- Раскладка по разделам ---------- */
  // Всё, что зависит от раскладки, считается здесь — при загрузке, изменении окна и размеров
  // страницы, а не в кадре. В кадре — только запомненные числа и положение прокрутки.

  // Место элемента в документе без учёта transform: поле ввода проявляется со сдвигом (.fade)
  function docBox(el) {
    var x = 0, y = 0, e = el;
    while (e) { x += e.offsetLeft; y += e.offsetTop; e = e.offsetParent; }
    return { x0: x, y0: y, x1: x + el.offsetWidth, y1: y + el.offsetHeight };
  }

  var anchors = [];
  function measure() {
    var vh = window.innerHeight, top = window.scrollY;
    anchors = Array.prototype.map.call(document.querySelectorAll('[data-shape]'), function (el) {
      var r = el.getBoundingClientRect(), t = el.querySelector('[data-flow-target]');
      var tgt = t ? docBox(t) : null, col = t && t.closest('.col');
      var hide = null;
      // Узкий экран: колонка текста во всю ширину, и поток к полю шёл бы сквозь заголовок и
      // абзац. Над ними (от верха колонки до поля) поток невидим и проявляется у самого поля.
      if (tgt && col && window.innerWidth < 900) {
        var cb = docBox(col);
        var prev = t.previousElementSibling; // текст прямо над полем: поток проявляется под ним
        hide = { x0: cb.x0 - 12, x1: cb.x1 + 12, y0: cb.y0 - 12, y1: prev ? docBox(prev).y1 + 4 : tgt.y0 - 14 };
        if (hide.y1 <= hide.y0) hide = null;
      }
      return {
        shape: el.getAttribute('data-shape'),
        place: el.getAttribute('data-place') || 'center',
        c: r.top + top + Math.min(r.height, vh * 1.4) / 2 - vh / 2,
        tgt: tgt, // куда течёт поток формы (поле ввода «Запрос»)
        hide: hide // где поток невидим (текст над полем на узком экране)
      };
    }).filter(function (a) { return META[a.shape]; });
  }

  function clamp01(v) { return Math.max(0, Math.min(1, v)); }

  // Текущая пара форм и прогресс перехода; у центра раздела форма держится собранной
  var TL = { a: null, b: null, p: 0 };
  function timeline(y) {
    var n = anchors.length;
    TL.p = 0;
    if (n === 1) { TL.a = TL.b = anchors[0]; return TL; }
    if (y <= anchors[0].c) { TL.a = anchors[0]; TL.b = anchors[1]; return TL; }
    for (var i = 0; i < n - 1; i++) {
      var A = anchors[i], B = anchors[i + 1];
      if (y < B.c) { TL.a = A; TL.b = B; TL.p = clamp01(((y - A.c) / Math.max(1, B.c - A.c) - 0.2) / 0.6); return TL; }
    }
    TL.a = anchors[n - 2]; TL.b = anchors[n - 1]; TL.p = 1;
    return TL;
  }

  function resize() {
    readSize();
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    gl.viewport(0, 0, canvas.width, canvas.height);
    bridgeCopies();
    measure();
  }

  // Прокрутка запоминается в обработчике, а не читается в кадре: чтение scrollY в кадре
  // заставляет браузер досчитывать раскладку
  var scrollTop = window.scrollY;
  window.addEventListener('scroll', function () { scrollTop = window.scrollY; }, { passive: true });

  var mouse = { x: 0, y: 0, tx: 0, ty: 0, nx: 9, ny: 9, tnx: 9, tny: 9 };
  window.addEventListener('pointermove', function (e) {
    mouse.tx = e.clientX / W * 2 - 1;
    mouse.ty = -(e.clientY / H * 2 - 1);
    if (e.pointerType === 'mouse') { mouse.tnx = mouse.tx; mouse.tny = mouse.ty; }
  }, { passive: true });
  document.addEventListener('pointerleave', function () { mouse.tnx = 9; mouse.tny = 9; });

  // Положение, масштаб и поворот формы — в заранее созданный массив (без мусора в кадре)
  function xf(anchor, time, out) {
    var m = META[anchor.shape], asp = W / H, hw = asp * 3.4 / 2.2, narrow = asp < 0.85;
    var x = 0, y = m.lift || 0, s = m.scale;
    if (m.wide) {
      s *= Math.min(1, hw * 1.9 / m.width); // центральные пролёты целиком, подходы — до краёв окна
      if (narrow) y = 0.72;
    } else if (m.model) {
      if (narrow) { y = 0.72; s *= Math.min(0.5, hw * 0.9 / 1.2); } // на телефоне — в верхней трети экрана
      else if (anchor.place === 'right') x = hw * (0.46 + (m.shift || 0));
      else if (anchor.place === 'left') x = -hw * (0.46 + (m.shift || 0));
    } else if (narrow) {
      s *= 0.6;
    }
    var ang = m.spin ? m.base + time * 0.16 : m.base + Math.sin(time * 0.35) * m.amp;
    out[0] = x; out[1] = y; out[2] = s; out[3] = ang + mouse.x * MOUSE_YAW;
    return out;
  }

  // Точка модели на экране (−1…1): те же повороты и перспектива, что в шейдере
  function project(v, X, tilt, out) {
    var c = Math.cos(X[3]), s = Math.sin(X[3]);
    var x = v[0] * X[2], y = v[1] * X[2], z = v[2] * X[2];
    var px = c * x + s * z + X[0], py = y + X[1], pz = -s * x + c * z;
    var ct = Math.cos(tilt), st = Math.sin(tilt);
    var qy = ct * py - st * pz, d = 3.4 - Math.min(st * py + ct * pz, 2.2);
    out[0] = px / (W / H) * 2.2 / d; out[1] = qy * 2.2 / d;
  }

  // «Система слушает»: на сколько сдвинуть конец потока, чтобы он упёрся в поле ввода там,
  // где поле сейчас на экране. Цель — точка поля, ближайшая к облаку (внутри скругления).
  var pSrc = [0, 0], pEnd = [0, 0];
  function aim(anchor, X, tilt, out) {
    out[0] = 0; out[1] = 0; out[2] = 0;
    var tail = META[anchor.shape].tail, b = anchor.tgt;
    if (!tail || !b) return out;
    out[2] = 1;
    project(tail.src, X, tilt, pSrc);
    project(tail.end, X, tilt, pEnd);
    var r = (b.y1 - b.y0) * 0.3;
    var cx = (pSrc[0] + 1) / 2 * W, cy = (1 - pSrc[1]) / 2 * H + scrollTop; // облако в координатах документа
    var px = Math.max(b.x0 + r, Math.min(b.x1 - r, cx));
    var py = Math.max(b.y0 + r, Math.min(b.y1 - r, cy)) - scrollTop;
    out[0] = px / W * 2 - 1 - pEnd[0];
    out[1] = Math.max(-1.08, Math.min(1.08, 1 - py / H * 2)) - pEnd[1]; // поле за краем экрана — тянемся к краю
    return out;
  }

  /* ---------- Кадр ---------- */

  var sy = scrollTop;
  var t0 = performance.now();
  var last = t0;
  // Доля сближения за кадр, пересчитанная на реальное время: при 60 кадрах/с — k
  function ease(k, dt) { return 1 - Math.pow(1 - k, dt * 60); }

  gl.disable(gl.DEPTH_TEST);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
  gl.clearColor(7 / 255, 8 / 255, 11 / 255, 1);
  // Постоянные значения задаются один раз: программа их помнит
  gl.useProgram(P.p);
  gl.uniform3fv(P.u.uPal, new Float32Array(PALETTE));
  gl.uniform1f(P.u.uSpread, reduced ? 0 : 0.95);
  gl.uniform1f(P.u.uAlpha, 0.8);
  gl.useProgram(S.p);
  gl.uniform1f(S.u.uAlpha, 1);

  var uA = new Float32Array(4), uB = new Float32Array(4), gA = new Float32Array(3), gB = new Float32Array(3);
  var hideRect = new Float32Array(4), NO_HIDE = new Float32Array([9, 9, 9.1, 9.1]);
  // Прямоугольник, где поток невидим, — в координатах экрана (по запомненной прокрутке)
  function hideOf(anchor) {
    var h = anchor.hide;
    if (!h || !META[anchor.shape].tail) return null;
    hideRect[0] = h.x0 / W * 2 - 1;
    hideRect[1] = 1 - (h.y1 - scrollTop) / H * 2;
    hideRect[2] = h.x1 / W * 2 - 1;
    hideRect[3] = 1 - (h.y0 - scrollTop) / H * 2;
    return hideRect;
  }

  function frame(now) {
    requestAnimationFrame(frame);
    var time = reduced ? 0 : (now - t0) / 1000;
    var dt = Math.min(1, Math.max(0, (now - last) / 1000));
    last = now;
    sy += (scrollTop - sy) * (reduced ? 1 : ease(0.085, dt));
    mouse.x += (mouse.tx - mouse.x) * ease(0.05, dt);
    mouse.y += (mouse.ty - mouse.y) * ease(0.05, dt);
    mouse.nx += (mouse.tnx - mouse.nx) * ease(0.25, dt);
    mouse.ny += (mouse.tny - mouse.ny) * ease(0.25, dt);

    var intro = reduced ? 0 : Math.pow(clamp01(1 - time / 2.6), 3);

    gl.clear(gl.COLOR_BUFFER_BIT);

    // Звёзды
    gl.useProgram(S.p);
    gl.uniform1f(S.u.uScroll, sy);
    gl.uniform1f(S.u.uTime, time);
    gl.uniform1f(S.u.uPx, 1.6 * dpr);
    attr(locS, starBuf);
    gl.drawArrays(gl.POINTS, 0, STARS);
    gl.disableVertexAttribArray(locS);

    // Форма
    if (anchors.length) {
      var tl = timeline(sy), tilt = 0.1 + mouse.y * 0.12;
      xf(tl.a, time, uA);
      xf(tl.b, time, uB);
      gl.useProgram(P.p);
      attr(locFrom, bufs[tl.a.shape]);
      attr(locTo, bufs[tl.b.shape]);
      attr(locRnd, rndBuf);
      gl.uniform1f(P.u.uP, tl.p);
      gl.uniform1f(P.u.uTime, time);
      gl.uniform1f(P.u.uIntro, intro);
      gl.uniform1f(P.u.uAspect, W / H);
      gl.uniform1f(P.u.uPx, (light ? 2.4 : 2.0) * dpr);
      gl.uniform1f(P.u.uTilt, tilt);
      gl.uniform4fv(P.u.uA, uA);
      gl.uniform4fv(P.u.uB, uB);
      gl.uniform3fv(P.u.uTgtA, aim(tl.a, uA, tilt, gA));
      gl.uniform3fv(P.u.uTgtB, aim(tl.b, uB, tilt, gB));
      gl.uniform4fv(P.u.uHide, hideOf(tl.a) || hideOf(tl.b) || NO_HIDE);
      gl.uniform2f(P.u.uHideSoft, 22 / W * 2, 10 / H * 2);
      gl.uniform2f(P.u.uMouse, mouse.nx, mouse.ny);
      gl.uniform2f(P.u.uShift, 0, 0);
      gl.uniform2f(P.u.uFade, 0, 0);
      gl.drawArrays(gl.POINTS, 0, N);
      // Мост во всю ширину: повторы периода слева и справа, пока форма видна
      var pa = META[tl.a.shape].period, pb = META[tl.b.shape].period, k;
      if (pa && tl.p < 1) {
        gl.uniform2f(P.u.uFade, 1, 0);
        for (k = -copies.l; k <= copies.r; k++) if (k) { gl.uniform2f(P.u.uShift, k * pa, 0); gl.drawArrays(gl.POINTS, 0, N); }
      }
      if (pb && tl.p > 0) {
        gl.uniform2f(P.u.uFade, 0, 1);
        for (k = -copies.l; k <= copies.r; k++) if (k) { gl.uniform2f(P.u.uShift, 0, k * pb); gl.drawArrays(gl.POINTS, 0, N); }
      }
      gl.disableVertexAttribArray(locFrom);
      gl.disableVertexAttribArray(locTo);
      gl.disableVertexAttribArray(locRnd);
    }
  }

  resize();
  window.addEventListener('resize', resize);
  window.addEventListener('load', measure);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(measure);
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(measure).observe(document.body);
  requestAnimationFrame(frame);
})();
