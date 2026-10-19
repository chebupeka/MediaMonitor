/**
 * Шейдеры — перенос `site/particles.js` без изменения смысла. Добавлено для приложения
 * (помечено «прил.»):
 *  - точки-данные (код +16, правило честности): крупнее и ярче декора, с мягким ореолом
 *    (город «загорается», как золотые облака сайта), без мерцания; раскладываются спиралью
 *    вокруг города с шагом в пикселях — их можно сосчитать при любой высоте блока;
 *  - светлая тема (uLight, uSoft): у сайта её нет, поправки — как в ветке;
 *  - звёзды гаснут к краям блока (uVignette): холст здесь — блок, а не всё окно, и ровное
 *    звёздное поле внутри блока читалось бы прямоугольником.
 * Общее с сайтом (исправления 19.10.2026): поток «система слушает» упирается в поле ввода
 * (uTgtA, uTgtB), мост во всю ширину — повторами периода (uShift, uFade).
 */

/** Точка-данные: во сколько раз крупнее средней точки и насколько мягче её край (ореол). */
const DATA_SIZE = '4.0';
const DATA_SOFT = '0.55';

export const VS = `
#define DATA_SIZE ${DATA_SIZE}
attribute vec4 aFrom;
attribute vec4 aTo;
attribute vec4 aRnd;
uniform float uP, uTime, uSpread, uIntro, uAspect, uPx, uTilt, uAlpha;
uniform vec4 uA;
uniform vec4 uB;
uniform vec2 uMouse;
uniform vec3 uPal[8];
uniform float uLight;   // прил.: 1 — светлая тема
uniform vec2 uView;     // прил.: размер холста в пикселях устройства
uniform float uDataPx;  // прил.: шаг спирали точек-данных в пикселях устройства
// «Система слушает»: на сколько сдвинуть конец потока, чтобы он упёрся в поле ввода
// (в координатах холста; для формы «откуда» и формы «куда», у остальных форм — 0)
uniform vec2 uTgtA;
uniform vec2 uTgtB;
// Повтор формы во всю ширину (мост): сдвиг модели «откуда» (x) и «куда» (y) на целое число
// периодов; uFade — повтор принадлежит форме «откуда» (x = 1) или «куда» (y = 1)
uniform vec2 uShift;
uniform vec2 uFade;
varying vec3 vCol;
varying float vAlpha;
varying float vData;    // прил.: 1 — точка-данные
vec3 rotY(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(c * p.x + s * p.z, p.y, -s * p.x + c * p.z); }
vec3 rotX(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(p.x, c * p.y - s * p.z, s * p.y + c * p.z); }
// прил.: точка-данные — код 16 и выше
float isData(float code) { return step(15.5, floor(code + 0.0001)); }
// Место текущей точки на пути (0…1); у точек, которые не текут, и у точек-данных — 0
float along(float code) {
  float idx = floor(code + 0.0001);
  return step(7.5, idx) * (1.0 - step(15.5, idx)) * (code - idx);
}
// прил.: место точки-данных в спирали вокруг города, в пикселях (номер — в дробной части кода)
vec2 spiral(float code) {
  float i = floor(fract(code) * 1000.0 + 0.5);
  float a = i * 2.399;
  return vec2(cos(a), sin(a)) * sqrt(i);
}
// Цвет и яркость точки по коду: палитра, «течение» импульсами, мерцание сбоя, приглушённые точки
vec4 look(float code, float d) {
  float idx = floor(code + 0.0001);
  float f = code - idx;
  idx -= 16.0 * step(15.5, idx); // прил.: точка-данные — цвет по палитре
  float flowing = step(7.5, idx);
  idx -= 8.0 * flowing;
  vec3 c = uPal[int(idx)];
  float a = 1.0;
  if (flowing > 0.5) { float w = fract(f * 5.0 - uTime * 0.42); a = 0.22 + 0.78 * pow(w, 6.0); }
  if (idx > 5.5 && idx < 6.5) a *= 0.3 + 0.7 * step(0.45, fract(sin(floor(uTime * 7.0) * 12.9898 + d * 78.233) * 43758.5453));
  if (idx > 6.5) a *= 0.5;
  return vec4(c, a);
}
void main() {
  float d = aRnd.w;
  float t = clamp((uP - d * 0.3) / 0.7, 0.0, 1.0);
  float e = t * t * (3.0 - 2.0 * t);
  vec3 a = rotY((aFrom.xyz + vec3(uShift.x, 0.0, 0.0)) * uA.z, uA.w); a.xy += uA.xy;
  vec3 b = rotY((aTo.xyz + vec3(uShift.y, 0.0, 0.0)) * uB.z, uB.w); b.xy += uB.xy;
  vec3 p = mix(a, b, e) + aRnd.xyz * uSpread * sin(3.14159 * e);
  p += 0.01 * vec3(sin(uTime * 1.3 + d * 40.0), cos(uTime * 1.1 + d * 31.0), sin(uTime * 0.9 + d * 17.0));
  p += aRnd.xyz * 4.0 * uIntro * (0.6 + d);
  p = rotX(p, uTilt);
  float z = 3.4 - min(p.z, 2.2);
  vec2 q = vec2(p.x / uAspect, p.y) * (2.2 / z);
  // поток изгибается к полю ввода: начало остаётся у облака, конец упирается в поле
  q += mix(along(aFrom.w) * uTgtA, along(aTo.w) * uTgtB, e);
  vec2 dm = (q - uMouse) * vec2(uAspect, 1.0);
  float dl = length(dm);
  q += dm / (dl + 1e-4) * 0.05 * smoothstep(0.28, 0.0, dl) * vec2(1.0 / uAspect, 1.0);
  // прил.: точки-данные — спиралью вокруг города, шаг в пикселях
  float da = isData(aFrom.w), db = isData(aTo.w);
  float data = mix(da, db, e);
  q += mix(spiral(aFrom.w) * da, spiral(aTo.w) * db, e) * uDataPx * 2.0 / uView;
  gl_Position = vec4(q, 0.0, 1.0);
  gl_PointSize = min(uPx * (3.4 / z) * mix(0.55 + d * 0.9, DATA_SIZE, data), 26.0);
  vData = data;
  vec4 la = look(aFrom.w, d), lb = look(aTo.w, d);
  vec3 col = mix(la.rgb, lb.rgb, e);
  if (d > 0.965 && data < 0.5) col = mix(col, vec3(0.93, 0.95, 1.0), 0.7 * (1.0 - uLight));
  vCol = col;
  vAlpha = uAlpha * mix(mix(la.a, lb.a, e), 1.0, data) * clamp(1.7 - z * 0.27, 0.25, 1.0) * (1.0 - uIntro * 0.5);
  vAlpha *= mix(1.0, 1.0 - e, uFade.x) * mix(1.0, e, uFade.y);
}`;

export const VS_STARS = `
attribute vec4 aS;
uniform float uScroll, uTime, uPx, uAlpha;
uniform float uVignette; // прил.: 1 — звёзды гаснут к краям блока (овалом, без прямых границ)
varying vec3 vCol;
varying float vAlpha;
varying float vData; // прил.: общий фрагментный шейдер; звёзды — не данные
void main() {
  vData = 0.0;
  float y = fract(aS.y + uScroll * (0.00004 + aS.z * 0.00016));
  vec2 pos = vec2(aS.x * 2.0 - 1.0, y * 2.0 - 1.0);
  gl_Position = vec4(pos, 0.0, 1.0);
  gl_PointSize = uPx * (0.7 + aS.z * 1.4);
  float tw = 0.55 + 0.45 * sin(uTime * (0.8 + aS.w * 2.5) + aS.w * 50.0);
  vAlpha = uAlpha * (0.25 + 0.6 * aS.z) * tw;
  vAlpha *= mix(1.0, smoothstep(1.0, 0.45, length(pos)), uVignette);
  vCol = aS.w < 0.12 ? vec3(0.45, 0.65, 1.0) : (aS.w < 0.22 ? vec3(1.0, 0.76, 0.38) : vec3(0.92, 0.94, 1.0));
}`;

export const FS = `
precision mediump float;
#define DATA_SOFT ${DATA_SOFT}
uniform float uSoft; // прил.: 3.2 — как на сайте; в светлой теме мягче
varying vec3 vCol;
varying float vAlpha;
varying float vData; // прил.: точка-данные — с мягким ореолом: город «загорается»
void main() {
  vec2 c = gl_PointCoord - 0.5;
  float r = dot(c, c) * 4.0;
  if (r > 1.0) discard;
  gl_FragColor = vec4(vCol, exp(-r * uSoft * mix(1.0, DATA_SOFT, vData)) * vAlpha);
}`;
