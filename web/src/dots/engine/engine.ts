/**
 * Движок точек — перенос `site/particles.js` (сайт «Медиарадар»): те же шейдеры, формы,
 * переходы, 3D-наклоны и вращение, реакция на курсор, вступление и звёзды.
 *
 * Отличие одно — чем управляется переход. На сайте форму задаёт прокрутка: точки
 * перелетают из формы раздела в форму следующего, прогресс p сглажен как прокрутка
 * (`ease(0.085)`). Здесь форму задаёт свойство компонента, а прокрутка «виртуальная»:
 * при смене формы цель равномерно проходит путь от формы к форме за SCROLL_S, прогресс
 * догоняет её тем же сглаживанием, что и на сайте. Повернули назад, к прежней форме, —
 * точки возвращаются, как при прокрутке вверх; новая форма посреди перелёта — сначала
 * долетают до текущей, потом летят дальше, как при прокрутке через несколько разделов.
 *
 * Холст — блок внутри страницы, а не весь экран: размеры, раскладка и мышь считаются
 * по нему; поворот от мыши — по окну, как на сайте.
 *
 * Кадр не читает раскладку (исправления 19.10.2026, как на сайте): размер холста приходит
 * из ResizeObserver (setSize), место холста и поля ввода на экране запоминаются при
 * прокрутке и изменении размеров. Массивы для uniform-ов создаются один раз.
 * Поток «система слушает» упирается в поле ввода (setTarget); мост — во всю ширину холста
 * повторами периода.
 */
import { FS, VS, VS_STARS } from './shaders';
import {
  META,
  PALETTE,
  buildShape,
  rng,
  shapeKey,
  type ShapeId,
  type ShapeRequest,
} from './shapes';

/** Слабое устройство — как `light` на сайте: меньше точек, точки крупнее. */
export function isLowPower(): boolean {
  if (typeof window === 'undefined') return false;
  return (
    Math.min(window.screen.width, window.screen.height) < 700 ||
    !!window.matchMedia?.('(pointer: coarse)').matches
  );
}

/** Точек на сайте (на весь экран) и звёзд — числа из particles.js. */
export const SITE_N = { normal: 20000, low: 9000 } as const;
export const SITE_STARS = { normal: 1400, low: 700 } as const;

/**
 * Путь «виртуальной прокрутки» от формы к форме, с. На сайте p идёт от 0 до 1 на 60 %
 * расстояния между разделами; при обычной прокрутке колесом это около секунды.
 */
const SCROLL_S = 1.1;
/** Шаг спирали точек-данных, CSS-пиксели (правило честности: точки можно сосчитать). */
const DATA_SPACING = 3.6;
/** Кэш буферов форм: старые формы с данными вытесняются. */
const CACHE_LIMIT = 24;
/** Поворот формы за мышью (как на сайте) */
const MOUSE_YAW = 0.25;
/** Прямоугольник «поток невидим» за пределами холста — то есть нигде */
const NO_HIDE = new Float32Array([9, 9, 9.1, 9.1]);

export interface EngineOptions {
  /** Число точек (бюджет) */
  count: number;
  /** Звёзды на фоне холста: 0 — без звёзд */
  stars: number;
  /** «Уменьшить движение»: формы сразу на месте, ничего не мерцает и не течёт, мышь не влияет */
  still: boolean;
  /** Слабое устройство (`light` сайта): точки крупнее */
  lowPower: boolean;
  /** Вступление сайта: точки слетаются из рассеяния за 2,6 с */
  intro: boolean;
  /** Где форма в блоке: по центру (или слева/справа, как разделы сайта) */
  place?: 'center' | 'left' | 'right';
}

/** Прямоугольник на экране (CSS-пиксели окна) */
interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

interface Program {
  p: WebGLProgram;
  u: Record<string, WebGLUniformLocation | null>;
}

interface Mouse {
  x: number;
  y: number;
  tx: number;
  ty: number;
  nx: number;
  ny: number;
  tnx: number;
  tny: number;
  /** Последняя позиция указателя в окне; null — указатель не мышь или ушёл со страницы */
  cx: number | null;
  cy: number | null;
}

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

/** Доля сближения за кадр, пересчитанная на реальное время: при 60 кадрах/с — k */
function ease(k: number, dt: number): number {
  return 1 - Math.pow(1 - k, dt * 60);
}

function hexToRgb(value: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(value.trim());
  if (!m?.[1]) return null;
  const n = parseInt(m[1], 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

export class DotsEngine {
  private gl: WebGLRenderingContext;
  private P!: Program;
  private S!: Program;
  private rndBuf: WebGLBuffer | null = null;
  private starBuf: WebGLBuffer | null = null;
  private readonly buffers = new Map<string, { buf: WebGLBuffer; id: ShapeId; used: number }>();
  private readonly requests = new Map<string, ShapeRequest>();
  private loc = { from: -1, to: -1, rnd: -1, s: -1 };

  // Переход: из формы `from` в форму `to`, p — прогресс, target — «виртуальная прокрутка»
  private from: string | null = null;
  private to: string | null = null;
  private p = 0;
  private target = 0;
  private dir: 0 | 1 | -1 = 0;
  private queued: string | null = null;

  private lightTheme = false;
  private palette: Float32Array = PALETTE;
  private visible = true;
  private lost = false;
  private raf = 0;
  private readonly t0 = performance.now();
  private last = performance.now();
  private frames = 0;
  private fpsT = performance.now();
  /** Кадров в секунду за последнюю секунду — для витрины и проверки */
  fps = 0;
  private readonly mouse: Mouse = {
    x: 0,
    y: 0,
    tx: 0,
    ty: 0,
    nx: 9,
    ny: 9,
    tnx: 9,
    tny: 9,
    cx: null,
    cy: null,
  };
  private readonly cleanup: (() => void)[] = [];

  // Размер холста (CSS-пиксели) — из ResizeObserver, не из раскладки в кадре
  private W = 0;
  private H = 0;
  /** Сколько повторов формы с периодом (мост) нужно слева и справа до краёв холста */
  private copies = { l: 1, r: 1 };
  // Место холста и поля ввода на экране — обновляются при прокрутке и изменении размеров
  private box: Box | null = null;
  private flowEl: Element | null = null;
  private flowBox: Box | null = null;
  // Текст над полем, сквозь который поток не идёт (невидим над ним, проявляется у поля)
  private coverEl: Element | null = null;
  private coverBox: Box | null = null;
  private boxDirty = true;
  private flowObserver: ResizeObserver | null = null;
  // Массивы для uniform-ов — один раз, без мусора в кадре
  private readonly uA = new Float32Array(4);
  private readonly uB = new Float32Array(4);
  private readonly gA = new Float32Array(3);
  private readonly gB = new Float32Array(3);
  private readonly hide = new Float32Array(4);
  private readonly pSrc = [0, 0];
  private readonly pEnd = [0, 0];

  private constructor(
    private readonly canvas: HTMLCanvasElement,
    gl: WebGLRenderingContext,
    private readonly opts: EngineOptions,
  ) {
    this.gl = gl;
    this.init();
    this.listen();
  }

  /** null — нет WebGL или шейдер не собрался: покажем статичную карту. */
  static create(canvas: HTMLCanvasElement, opts: EngineOptions): DotsEngine | null {
    const gl = canvas.getContext('webgl', {
      antialias: false,
      alpha: true,
      premultipliedAlpha: true,
      depth: false,
      powerPreference: 'high-performance',
    });
    if (!gl || gl.isContextLost()) return null;
    try {
      return new DotsEngine(canvas, gl, opts);
    } catch (err) {
      console.error(err);
      return null;
    }
  }

  get count(): number {
    return this.opts.count;
  }

  /** Для витрины и проверки: текущий перелёт */
  get state(): { from: string | null; to: string | null; p: number } {
    return { from: this.from, to: this.to, p: this.p };
  }

  /* ---------- Ресурсы WebGL ---------- */

  private program(vs: string, fs: string): Program {
    const gl = this.gl;
    const sh = (type: number, src: string) => {
      const s = gl.createShader(type);
      if (!s) throw new Error('WebGL: шейдер не создан');
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
        throw new Error(gl.getShaderInfoLog(s) ?? 'WebGL: шейдер не собрался');
      return s;
    };
    const p = gl.createProgram();
    if (!p) throw new Error('WebGL: программа не создана');
    gl.attachShader(p, sh(gl.VERTEX_SHADER, vs));
    gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS))
      throw new Error(gl.getProgramInfoLog(p) ?? 'WebGL: программа не собралась');
    const u: Program['u'] = {};
    const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS) as number;
    for (let i = 0; i < n; i += 1) {
      const info = gl.getActiveUniform(p, i);
      if (info) u[info.name.replace('[0]', '')] = gl.getUniformLocation(p, info.name);
    }
    return { p, u };
  }

  private buffer(data: Float32Array): WebGLBuffer {
    const gl = this.gl;
    const b = gl.createBuffer();
    if (!b) throw new Error('WebGL: буфер не создан');
    gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    return b;
  }

  /** Программы и общие буферы; после потери контекста — заново. */
  private init(): void {
    const gl = this.gl;
    this.P = this.program(VS, FS);
    this.S = this.program(VS_STARS, FS);
    this.loc = {
      from: gl.getAttribLocation(this.P.p, 'aFrom'),
      to: gl.getAttribLocation(this.P.p, 'aTo'),
      rnd: gl.getAttribLocation(this.P.p, 'aRnd'),
      s: gl.getAttribLocation(this.S.p, 'aS'),
    };
    // Случайные числа точек — как на сайте: направление разлёта и «характер» d
    const R = rng(20261019 ^ this.opts.count);
    const N = this.opts.count;
    const rnd = new Float32Array(N * 4);
    for (let i = 0; i < N; i += 1) {
      const z = 2 * R() - 1;
      const ph = 2 * Math.PI * R();
      const s = Math.sqrt(1 - z * z);
      const m = 0.4 + R() * 0.9;
      rnd[i * 4] = s * Math.cos(ph) * m;
      rnd[i * 4 + 1] = s * Math.sin(ph) * m;
      rnd[i * 4 + 2] = z * m;
      rnd[i * 4 + 3] = R();
    }
    this.rndBuf = this.buffer(rnd);
    const STARS = this.opts.stars;
    if (STARS > 0) {
      const stars = new Float32Array(STARS * 4);
      for (let j = 0; j < STARS; j += 1) {
        stars[j * 4] = R();
        stars[j * 4 + 1] = R();
        stars[j * 4 + 2] = Math.pow(R(), 2.2);
        stars[j * 4 + 3] = R();
      }
      this.starBuf = this.buffer(stars);
    }
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
  }

  private listen(): void {
    const onMove = (e: PointerEvent) => {
      this.mouse.tx = (e.clientX / window.innerWidth) * 2 - 1;
      this.mouse.ty = -((e.clientY / window.innerHeight) * 2 - 1);
      if (e.pointerType === 'mouse') {
        this.mouse.cx = e.clientX;
        this.mouse.cy = e.clientY;
      }
    };
    const onLeave = () => {
      this.mouse.cx = null;
      this.mouse.cy = null;
    };
    const onLost = (e: Event) => {
      e.preventDefault(); // дать браузеру вернуть контекст
      this.lost = true;
      cancelAnimationFrame(this.raf);
      this.raf = 0;
    };
    const onRestored = () => {
      this.lost = false;
      this.buffers.clear(); // старые буферы умерли вместе с контекстом
      this.starBuf = null;
      try {
        this.init();
      } catch (err) {
        console.error(err);
        return;
      }
      this.start();
    };
    // Прокрутка любого контейнера двигает холст и поле ввода — их место перечитаем один раз,
    // в обработчике прокрутки, а не в каждом кадре
    const onScroll = () => {
      this.boxDirty = true;
      if (this.mouse.cx !== null || this.flowEl) this.readBoxes();
    };
    window.addEventListener('pointermove', onMove, { passive: true });
    window.addEventListener('scroll', onScroll, { capture: true, passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    document.addEventListener('pointerleave', onLeave);
    // прил.: указатель ушёл из окна — отталкивание гаснет (на сайте холст и есть окно)
    document.documentElement.addEventListener('pointerleave', onLeave);
    this.canvas.addEventListener('webglcontextlost', onLost);
    this.canvas.addEventListener('webglcontextrestored', onRestored);
    this.cleanup.push(() => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('scroll', onScroll, { capture: true });
      window.removeEventListener('resize', onScroll);
      document.removeEventListener('pointerleave', onLeave);
      document.documentElement.removeEventListener('pointerleave', onLeave);
      this.canvas.removeEventListener('webglcontextlost', onLost);
      this.canvas.removeEventListener('webglcontextrestored', onRestored);
    });
  }

  /* ---------- Размер, место на экране, поле ввода ---------- */

  /** Размер холста в CSS-пикселях — из ResizeObserver обёртки. */
  setSize(w: number, h: number): void {
    if (w === this.W && h === this.H) return;
    this.W = w;
    this.H = h;
    this.boxDirty = true;
    this.countCopies();
    this.start();
  }

  /**
   * Поле ввода, к которому течёт поток формы «система слушает» (null — поток как в модели),
   * и текст над полем (cover), сквозь который поток не идёт: над ним поток невидим и
   * проявляется у самого поля. Места запоминаются при прокрутке и изменении размеров.
   */
  setTarget(el: Element | null, cover: Element | null = null): void {
    if (el === this.flowEl && cover === this.coverEl) return;
    this.flowObserver?.disconnect();
    this.flowObserver = null;
    this.flowEl = el;
    this.flowBox = null;
    this.coverEl = el ? cover : null;
    this.coverBox = null;
    this.boxDirty = true;
    if (el && typeof ResizeObserver !== 'undefined') {
      this.flowObserver = new ResizeObserver(() => {
        this.boxDirty = true;
        this.start();
      });
      this.flowObserver.observe(el);
      if (this.coverEl) this.flowObserver.observe(this.coverEl);
    }
    this.start();
  }

  /** Место холста и поля на экране: при прокрутке, изменении размеров и смене поля. */
  private readBoxes(): void {
    this.boxDirty = false;
    const r = this.canvas.getBoundingClientRect();
    this.box = { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
    if (this.flowEl?.isConnected) {
      const t = this.flowEl.getBoundingClientRect();
      this.flowBox = { left: t.left, top: t.top, right: t.right, bottom: t.bottom };
    } else this.flowBox = null;
    if (this.coverEl?.isConnected) {
      const c = this.coverEl.getBoundingClientRect();
      this.coverBox = { left: c.left, top: c.top, right: c.right, bottom: c.bottom };
    } else this.coverBox = null;
  }

  /** Где поток невидим — текст над полем, в координатах холста; null — нигде. */
  private hideRect(id: ShapeId): Float32Array | null {
    const b = this.box;
    const c = this.coverBox;
    if (!META[id].tail || !b || !c || this.W === 0 || this.H === 0) return null;
    const m = 12; // запас вокруг текста, CSS-пиксели
    this.hide[0] = ((c.left - m - b.left) / this.W) * 2 - 1;
    this.hide[1] = 1 - ((c.bottom + 4 - b.top) / this.H) * 2;
    this.hide[2] = ((c.right + m - b.left) / this.W) * 2 - 1;
    this.hide[3] = 1 - ((c.top - m - b.top) / this.H) * 2;
    return this.hide;
  }

  /**
   * Сколько повторов периода (мост) нужно слева и справа, чтобы настил доходил до краёв
   * холста при любом развороте формы — своём (base ± amp) и за мышью.
   */
  private countCopies(): void {
    const m = META.bridge;
    if (!m.period || this.W === 0 || this.H === 0) return;
    const asp = this.W / this.H;
    const hw = (asp * 3.4) / 2.2;
    const G = 1.06; // запас за край
    const s = m.scale * Math.min(1, (hw * 1.9) / (m.width ?? 1));
    // половина длины (в единицах модели) до края, который уходит вглубь; sn — синус разворота
    const need = (sn: number) => {
      const d = 2.2 * Math.sqrt(1 - sn * sn) - G * asp * sn;
      return d > 0.3 ? Math.min(16, (3.4 * G * asp) / d / s) : 16;
    };
    const aMin = m.base - (m.amp ?? 0) - MOUSE_YAW;
    const aMax = m.base + (m.amp ?? 0) + MOUSE_YAW;
    this.copies = {
      l: Math.max(1, Math.ceil((need(-Math.sin(aMin)) - 2.2) / m.period)),
      r: Math.max(1, Math.ceil((need(Math.sin(aMax)) - 2.2) / m.period)),
    };
  }

  /* ---------- Формы и переходы ---------- */

  /** Буфер формы: собирается один раз, живёт в кэше. */
  private bufferFor(key: string): WebGLBuffer | null {
    const hit = this.buffers.get(key);
    if (hit) {
      hit.used = performance.now();
      return hit.buf;
    }
    const req = this.requests.get(key);
    if (!req || this.lost) return null;
    const buf = this.buffer(buildShape(req, this.opts.count));
    this.buffers.set(key, { buf, id: req.id, used: performance.now() });
    this.evict();
    return buf;
  }

  private evict(): void {
    if (this.buffers.size <= CACHE_LIMIT) return;
    const keep = new Set([this.from, this.to, this.queued]);
    const old = [...this.buffers.entries()]
      .filter(([k]) => !keep.has(k))
      .sort((a, b) => a[1].used - b[1].used);
    for (const [k, v] of old.slice(0, this.buffers.size - CACHE_LIMIT)) {
      this.gl.deleteBuffer(v.buf);
      this.buffers.delete(k);
      this.requests.delete(k);
    }
  }

  /** Новая форма: точки перелетают в неё — как при прокрутке к следующему разделу. */
  setShape(req: ShapeRequest): void {
    const key = shapeKey(req);
    this.requests.set(key, req);
    if (this.opts.still || this.from === null || this.to === null) {
      // Без движения (и при первом показе) — форма сразу на месте
      this.from = key;
      this.to = key;
      this.p = 0;
      this.target = 0;
      this.dir = 0;
      this.queued = null;
    } else if (key === this.to) {
      this.queued = null;
      if (this.from !== this.to) this.dir = 1; // передумали возвращаться
    } else if (key === this.from && this.from !== this.to) {
      this.queued = null;
      this.dir = -1; // назад, как прокрутка вверх
    } else if (this.from === this.to || this.p < 0.02) {
      // в покое (или перелёт ещё не начался) — летим из текущей формы в новую
      this.to = key;
      this.dir = 1;
    } else {
      this.queued = key; // сначала долетим до текущей цели
    }
    this.bufferFor(key);
    this.start();
  }

  /** Двигает «виртуальную прокрутку» и прогресс перехода. */
  private advance(dt: number): void {
    if (this.from === this.to || this.dir === 0) return;
    this.target = clamp01(this.target + (this.dir * dt) / SCROLL_S);
    this.p += (this.target - this.p) * ease(0.085, dt);
    const end = this.dir > 0 ? 1 : 0;
    if (this.target !== end || Math.abs(this.p - end) > 0.002) return;
    // Долетели: форма собрана
    if (end === 1) this.from = this.to;
    else this.to = this.from;
    this.p = 0;
    this.target = 0;
    this.dir = 0;
    if (this.queued && this.queued !== this.from) {
      this.to = this.queued;
      this.dir = 1;
    }
    this.queued = null;
  }

  /** Положение, масштаб и поворот формы — `xf` сайта для блока вместо окна (в готовый массив). */
  private xf(id: ShapeId, time: number, W: number, H: number, out: Float32Array): Float32Array {
    const m = META[id];
    const asp = W / H;
    const hw = (asp * 3.4) / 2.2;
    const narrow = asp < 0.85;
    let x = 0;
    const y = m.lift ?? 0;
    let s = m.scale;
    if (m.wide) {
      s *= Math.min(1, (hw * 1.9) / (m.width ?? 1)); // во всю ширину, но целиком
    } else if (m.model) {
      // На сайте узкий экран (телефон) поднимает форму над текстом и уменьшает вдвое;
      // в блоке текста поверх нет — форма просто вписывается по ширине той же формулой.
      s *= Math.min(1, (hw * 0.9) / 1.2);
      const place = this.opts.place ?? 'center';
      if (place === 'right') x = hw * (0.46 + (m.shift ?? 0));
      else if (place === 'left') x = -hw * (0.46 + (m.shift ?? 0));
    } else if (narrow) {
      s *= 0.6;
    }
    const ang = m.spin ? m.base + time * 0.16 : m.base + Math.sin(time * 0.35) * (m.amp ?? 0);
    out[0] = x;
    out[1] = y;
    out[2] = s;
    out[3] = ang + this.mouse.x * MOUSE_YAW;
    return out;
  }

  /** Точка модели на холсте (−1…1): те же повороты и перспектива, что в шейдере. */
  private project(
    v: readonly [number, number, number],
    X: Float32Array,
    tilt: number,
    asp: number,
    out: number[],
  ): void {
    const c = Math.cos(X[3] ?? 0);
    const s = Math.sin(X[3] ?? 0);
    const k = X[2] ?? 1;
    const x = v[0] * k;
    const y = v[1] * k;
    const z = v[2] * k;
    const px = c * x + s * z + (X[0] ?? 0);
    const py = y + (X[1] ?? 0);
    const pz = -s * x + c * z;
    const ct = Math.cos(tilt);
    const st = Math.sin(tilt);
    const d = 3.4 - Math.min(st * py + ct * pz, 2.2);
    out[0] = ((px / asp) * 2.2) / d;
    out[1] = ((ct * py - st * pz) * 2.2) / d;
  }

  /**
   * «Система слушает»: на сколько сдвинуть конец потока, чтобы он упёрся в поле ввода там,
   * где поле сейчас. Цель — точка поля, ближайшая к облаку; поле за краем холста — поток
   * тянется к этому краю.
   */
  private aim(id: ShapeId, X: Float32Array, tilt: number, out: Float32Array): Float32Array {
    out[0] = 0;
    out[1] = 0;
    out[2] = 0;
    const tail = META[id].tail;
    const b = this.box;
    const t = this.flowBox;
    if (!tail || !b || !t || this.W === 0 || this.H === 0) return out;
    out[2] = 1;
    const W = this.W;
    const H = this.H;
    this.project(tail.src, X, tilt, W / H, this.pSrc);
    this.project(tail.end, X, tilt, W / H, this.pEnd);
    // облако и поле — в пикселях холста
    const cx = (((this.pSrc[0] ?? 0) + 1) / 2) * W;
    const cy = ((1 - (this.pSrc[1] ?? 0)) / 2) * H;
    const r = (t.bottom - t.top) * 0.3;
    const x0 = t.left - b.left + r;
    const x1 = Math.max(x0, t.right - b.left - r);
    const y0 = t.top - b.top + r;
    const y1 = Math.max(y0, t.bottom - b.top - r);
    const px = Math.max(x0, Math.min(x1, cx));
    const py = Math.max(y0, Math.min(y1, cy));
    const tx = Math.max(-0.95, Math.min(0.95, (px / W) * 2 - 1));
    const ty = Math.max(-0.9, Math.min(0.9, 1 - (py / H) * 2)); // края холста гаснут (маска)
    out[0] = tx - (this.pEnd[0] ?? 0);
    out[1] = ty - (this.pEnd[1] ?? 0);
    return out;
  }

  /* ---------- Кадр ---------- */

  setTheme(light: boolean): void {
    if (light === this.lightTheme) return;
    this.lightTheme = light;
    this.palette = light ? this.lightPalette() : PALETTE;
    this.start();
  }

  /** На светлом фоне светлые точки теряются — тёмные насыщенные цвета (как в ветке). */
  private lightPalette(): Float32Array {
    const css = getComputedStyle(this.canvas);
    const pal = Array.from(PALETTE);
    const set = (i: number, rgb: readonly number[]) => pal.splice(i * 3, 3, ...rgb);
    set(0, [0.13, 0.33, 0.8]);
    set(1, [0.2, 0.25, 0.34]);
    set(2, [0.82, 0.5, 0.0]);
    set(3, hexToRgb(css.getPropertyValue('--color-vk')) ?? [0.22, 0.52, 1.0]);
    set(4, hexToRgb(css.getPropertyValue('--color-ok')) ?? [1.0, 0.5, 0.2]);
    set(5, hexToRgb(css.getPropertyValue('--color-max')) ?? [0.18, 0.86, 0.55]);
    set(7, [0.42, 0.5, 0.62]);
    return new Float32Array(pal);
  }

  setVisible(visible: boolean): void {
    this.visible = visible;
    if (visible) this.start();
  }

  /** Перерисовать (например, после смены размера без движения). */
  redraw(): void {
    this.start();
  }

  private start(): void {
    if (!this.raf && !this.lost) this.raf = requestAnimationFrame((t) => this.frame(t));
  }

  private attr(loc: number, buf: WebGLBuffer): void {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 4, gl.FLOAT, false, 0, 0);
  }

  private frame(now: number): void {
    this.raf = 0;
    if (!this.visible || this.lost) {
      this.last = now;
      return;
    }
    const still = this.opts.still;
    const gl = this.gl;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    // Размер — из ResizeObserver; раскладку читаем, только если его ещё не сообщили
    if (this.W === 0 || this.H === 0)
      this.setSize(this.canvas.clientWidth, this.canvas.clientHeight);
    const W = this.W;
    const H = this.H;
    if (W === 0 || H === 0) {
      this.last = now;
      return; // экран скрыт — рисовать нечего
    }
    const cw = Math.round(W * dpr);
    const ch = Math.round(H * dpr);
    if (this.canvas.width !== cw || this.canvas.height !== ch) {
      this.canvas.width = cw;
      this.canvas.height = ch;
    }

    const time = still ? 0 : (now - this.t0) / 1000;
    const dt = Math.min(1, Math.max(0, (now - this.last) / 1000));
    this.last = now;
    this.advance(dt);
    const mouse = this.mouse;
    if (!still) {
      // Мышь: поворот — по окну, отталкивание — по холсту (в долях холста, −1…1)
      if (mouse.cx !== null && mouse.cy !== null) {
        // место холста — только после прокрутки или изменения размеров, не каждый кадр
        if (this.boxDirty || !this.box) this.readBoxes();
        const r = this.box ?? { left: 0, top: 0 };
        mouse.tnx = ((mouse.cx - r.left) / W) * 2 - 1;
        mouse.tny = -(((mouse.cy - r.top) / H) * 2 - 1);
      } else {
        mouse.tnx = 9;
        mouse.tny = 9;
      }
      mouse.x += (mouse.tx - mouse.x) * ease(0.05, dt);
      mouse.y += (mouse.ty - mouse.y) * ease(0.05, dt);
      mouse.nx += (mouse.tnx - mouse.nx) * ease(0.25, dt);
      mouse.ny += (mouse.tny - mouse.ny) * ease(0.25, dt);
    }
    const intro = still || !this.opts.intro ? 0 : Math.pow(clamp01(1 - time / 2.6), 3);
    const light = this.lightTheme;

    gl.viewport(0, 0, cw, ch);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    // Тёмная тема — свечение сложением, как на сайте; светлая — обычное наложение (ветка)
    if (light)
      gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    else gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE, gl.ONE, gl.ONE);

    // Звёзды (на сайте — во весь экран; здесь — только в блоке и только в тёмной теме)
    const S = this.S;
    if (this.starBuf && !light) {
      gl.useProgram(S.p);
      gl.uniform1f(S.u.uScroll ?? null, 0);
      gl.uniform1f(S.u.uTime ?? null, time);
      gl.uniform1f(S.u.uPx ?? null, 1.6 * dpr);
      gl.uniform1f(S.u.uAlpha ?? null, 1);
      gl.uniform1f(S.u.uSoft ?? null, 3.2);
      gl.uniform1f(S.u.uVignette ?? null, 1);
      this.attr(this.loc.s, this.starBuf);
      gl.drawArrays(gl.POINTS, 0, this.opts.stars);
      gl.disableVertexAttribArray(this.loc.s);
    }

    // Форма
    const from = this.from;
    const to = this.to;
    const bufA = from ? this.bufferFor(from) : null;
    const bufB = to ? this.bufferFor(to) : null;
    const idA = from ? this.buffers.get(from)?.id : undefined;
    const idB = to ? this.buffers.get(to)?.id : undefined;
    if (bufA && bufB && idA && idB && this.rndBuf) {
      const P = this.P;
      const tilt = 0.1 + mouse.y * 0.12;
      const p = from === to ? 0 : this.p;
      // место поля ввода — только после прокрутки, изменения размеров или смены поля
      if (this.flowEl && (this.boxDirty || !this.flowBox) && (META[idA].tail || META[idB].tail))
        this.readBoxes();
      gl.useProgram(P.p);
      this.attr(this.loc.from, bufA);
      this.attr(this.loc.to, bufB);
      this.attr(this.loc.rnd, this.rndBuf);
      gl.uniform1f(P.u.uP ?? null, p);
      gl.uniform1f(P.u.uTime ?? null, time);
      gl.uniform1f(P.u.uSpread ?? null, still ? 0 : 0.95);
      gl.uniform1f(P.u.uIntro ?? null, intro);
      gl.uniform1f(P.u.uAspect ?? null, W / H);
      gl.uniform1f(P.u.uPx ?? null, (this.opts.lowPower ? 2.4 : 2.0) * dpr * (light ? 1.2 : 1));
      gl.uniform1f(P.u.uTilt ?? null, tilt);
      gl.uniform1f(P.u.uAlpha ?? null, light ? 1 : 0.8);
      const uA = this.xf(idA, time, W, H, this.uA);
      const uB = this.xf(idB, time, W, H, this.uB);
      gl.uniform4fv(P.u.uA ?? null, uA);
      gl.uniform4fv(P.u.uB ?? null, uB);
      gl.uniform3fv(P.u.uTgtA ?? null, this.aim(idA, uA, tilt, this.gA));
      gl.uniform3fv(P.u.uTgtB ?? null, this.aim(idB, uB, tilt, this.gB));
      gl.uniform4fv(P.u.uHide ?? null, this.hideRect(idA) ?? this.hideRect(idB) ?? NO_HIDE);
      gl.uniform2f(P.u.uHideSoft ?? null, (22 / W) * 2, (10 / H) * 2);
      gl.uniform2f(P.u.uShift ?? null, 0, 0);
      gl.uniform2f(P.u.uFade ?? null, 0, 0);
      gl.uniform2f(P.u.uMouse ?? null, still ? 9 : mouse.nx, still ? 9 : mouse.ny);
      gl.uniform3fv(P.u.uPal ?? null, this.palette);
      gl.uniform1f(P.u.uLight ?? null, light ? 1 : 0);
      gl.uniform2f(P.u.uView ?? null, cw, ch);
      gl.uniform1f(P.u.uDataPx ?? null, DATA_SPACING * dpr);
      gl.uniform1f(P.u.uSoft ?? null, light ? 1.6 : 3.2);
      gl.drawArrays(gl.POINTS, 0, this.opts.count);
      // Форма с периодом (мост) — во всю ширину холста: повторы слева и справа, пока она видна
      const pa = META[idA].period;
      const pb = from === to ? undefined : META[idB].period;
      if (pa && p < 1) this.drawCopies(pa, 0);
      if (pb && p > 0) this.drawCopies(pb, 1);
      gl.disableVertexAttribArray(this.loc.from);
      gl.disableVertexAttribArray(this.loc.to);
      gl.disableVertexAttribArray(this.loc.rnd);
    }

    this.frames += 1;
    if (now - this.fpsT >= 1000) {
      this.fps = Math.round((this.frames * 1000) / (now - this.fpsT));
      this.frames = 0;
      this.fpsT = now;
    }
    // Без движения — один кадр на изменение
    if (!still) this.start();
  }

  /** Повторы формы с периодом: side 0 — форма «откуда», 1 — «куда». */
  private drawCopies(period: number, side: 0 | 1): void {
    const gl = this.gl;
    const u = this.P.u;
    gl.uniform2f(u.uFade ?? null, side === 0 ? 1 : 0, side === 1 ? 1 : 0);
    for (let k = -this.copies.l; k <= this.copies.r; k += 1) {
      if (k === 0) continue;
      gl.uniform2f(u.uShift ?? null, side === 0 ? k * period : 0, side === 1 ? k * period : 0);
      gl.drawArrays(gl.POINTS, 0, this.opts.count);
    }
  }

  destroy(): void {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    for (const off of this.cleanup) off();
    this.flowObserver?.disconnect();
    this.flowObserver = null;
    this.flowEl = null;
    this.coverEl = null;
    const gl = this.gl;
    if (!gl.isContextLost()) {
      for (const v of this.buffers.values()) gl.deleteBuffer(v.buf);
      if (this.rndBuf) gl.deleteBuffer(this.rndBuf);
      if (this.starBuf) gl.deleteBuffer(this.starBuf);
      gl.deleteProgram(this.P.p);
      gl.deleteProgram(this.S.p);
    }
    this.buffers.clear();
    // Холст создаётся заново при каждом монтировании (ParticleField), поэтому контекст можно
    // отпустить сразу: браузер держит ограниченное число живых контекстов.
    gl.getExtension('WEBGL_lose_context')?.loseContext();
  }
}
