/**
 * WebGL-сцена точек без библиотек — облегчённый движок сайта «Медиарадар».
 * Точки перелетают из прежней формы в новую за MORPH_MS, разлетаясь по пути.
 * Цвета площадок берутся из токенов (--color-vk, --color-ok, --color-max).
 */

const MORPH_MS = 1300;

const VS = `
attribute vec4 aFrom;
attribute vec4 aTo;
attribute vec4 aRnd;
uniform float uP, uTime, uSpread, uAspect, uPx, uAngle, uScale, uAlpha;
uniform vec3 uPal[8];
uniform float uLight;
varying vec3 vCol;
varying float vAlpha;
vec3 rotY(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(c * p.x + s * p.z, p.y, -s * p.x + c * p.z); }
vec3 rotX(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(p.x, c * p.y - s * p.z, s * p.y + c * p.z); }
// x: цвет, y: яркость, z: размер — по коду точки (палитра, «течение», данные, мерцание сбоя)
vec3 look(float code, float d, out vec3 c) {
  float idx = floor(code + 0.0001);
  float f = code - idx;
  float data = step(15.5, idx);
  idx -= 16.0 * data;
  float flowing = step(7.5, idx);
  idx -= 8.0 * flowing;
  c = uPal[int(idx)];
  float a = 1.0;
  if (flowing > 0.5) { float w = fract(f * 5.0 - uTime * 0.42); a = 0.22 + 0.78 * pow(w, 6.0); }
  if (idx > 5.5 && idx < 6.5) a *= 0.3 + 0.7 * step(0.45, fract(sin(floor(uTime * 7.0) * 12.9898 + d * 78.233) * 43758.5453));
  if (idx > 6.5) a *= 0.5;
  return vec3(0.0, a, data);
}
void main() {
  float d = aRnd.w;
  float t = clamp((uP - d * 0.3) / 0.7, 0.0, 1.0);
  float e = t * t * (3.0 - 2.0 * t);
  vec3 p = mix(aFrom.xyz, aTo.xyz, e) + aRnd.xyz * uSpread * sin(3.14159 * e);
  p += 0.008 * vec3(sin(uTime * 1.3 + d * 40.0), cos(uTime * 1.1 + d * 31.0), sin(uTime * 0.9 + d * 17.0));
  p = rotX(rotY(p * uScale, uAngle), 0.1);
  float z = 3.4 - min(p.z, 2.2);
  gl_Position = vec4(vec2(p.x / uAspect, p.y) * (2.2 / z), 0.0, 1.0);
  vec3 ca, cb;
  vec3 la = look(aFrom.w, d, ca);
  vec3 lb = look(aTo.w, d, cb);
  float data = mix(la.z, lb.z, e);
  gl_PointSize = min(uPx * (3.4 / z) * mix(0.55 + d * 0.9, 3.2, data), 22.0);
  vec3 col = mix(ca, cb, e);
  if (d > 0.965 && data < 0.5) col = mix(col, vec3(0.93, 0.95, 1.0), 0.7 * (1.0 - uLight));
  vCol = col;
  vAlpha = uAlpha * mix(mix(la.y, lb.y, e), 1.0, data) * clamp(1.7 - z * 0.27, 0.25, 1.0);
}`;

const FS = `
precision mediump float;
uniform float uSoft;
varying vec3 vCol;
varying float vAlpha;
void main() {
  vec2 c = gl_PointCoord - 0.5;
  float r = dot(c, c) * 4.0;
  if (r > 1.0) discard;
  gl_FragColor = vec4(vCol, exp(-r * uSoft) * vAlpha);
}`;

export interface SceneOptions {
  count: number;
  /** Без движения: формы сразу на месте, ничего не мерцает и не течёт */
  still: boolean;
}

export interface SceneLook {
  /** Масштаб формы и покачивание вокруг вертикали */
  scale: number;
  angle: number;
  sway: number;
  light: boolean;
}

function hexToRgb(value: string, fallback: [number, number, number]): [number, number, number] {
  const m = /^#?([0-9a-f]{6})$/i.exec(value.trim());
  if (!m?.[1]) return fallback;
  const n = parseInt(m[1], 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

function seeded(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export class ParticleScene {
  private readonly gl: WebGLRenderingContext;
  private readonly program: WebGLProgram;
  private readonly loc: Record<string, WebGLUniformLocation | null> = {};
  private readonly attr: { from: number; to: number; rnd: number };
  private readonly rndBuf: WebGLBuffer;
  private readonly buffers = new Map<string, WebGLBuffer>();
  private fromBuf: WebGLBuffer | null = null;
  private toBuf: WebGLBuffer | null = null;
  private morphStart = 0;
  private look: SceneLook = { scale: 1, angle: 0, sway: 0.2, light: false };
  private palette = new Float32Array(24);
  private raf = 0;
  private visible = true;
  private readonly t0 = performance.now();

  private constructor(
    private readonly canvas: HTMLCanvasElement,
    gl: WebGLRenderingContext,
    private readonly opts: SceneOptions,
  ) {
    this.gl = gl;
    this.program = ParticleScene.compile(gl);
    for (const name of [
      'uP',
      'uTime',
      'uSpread',
      'uAspect',
      'uPx',
      'uAngle',
      'uScale',
      'uAlpha',
      'uPal',
      'uLight',
      'uSoft',
    ])
      this.loc[name] = gl.getUniformLocation(this.program, name);
    this.attr = {
      from: gl.getAttribLocation(this.program, 'aFrom'),
      to: gl.getAttribLocation(this.program, 'aTo'),
      rnd: gl.getAttribLocation(this.program, 'aRnd'),
    };
    const R = seeded(7);
    const rnd = new Float32Array(opts.count * 4);
    for (let i = 0; i < opts.count; i += 1) {
      const z = 2 * R() - 1;
      const ph = 2 * Math.PI * R();
      const s = Math.sqrt(1 - z * z);
      const m = 0.4 + R() * 0.9;
      rnd[i * 4] = s * Math.cos(ph) * m;
      rnd[i * 4 + 1] = s * Math.sin(ph) * m;
      rnd[i * 4 + 2] = z * m;
      rnd[i * 4 + 3] = R();
    }
    this.rndBuf = this.upload(rnd);
    this.readPalette();
  }

  /** null — нет WebGL или шейдер не собрался: экран покажет статичную карту. */
  static create(canvas: HTMLCanvasElement, opts: SceneOptions): ParticleScene | null {
    const gl = canvas.getContext('webgl', {
      antialias: false,
      alpha: true,
      premultipliedAlpha: true,
      depth: false,
    });
    if (!gl) return null;
    try {
      return new ParticleScene(canvas, gl, opts);
    } catch {
      return null;
    }
  }

  private static compile(gl: WebGLRenderingContext): WebGLProgram {
    const shader = (type: number, src: string) => {
      const s = gl.createShader(type);
      if (!s) throw new Error('shader');
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
        throw new Error(gl.getShaderInfoLog(s) ?? 'shader');
      return s;
    };
    const p = gl.createProgram();
    if (!p) throw new Error('program');
    gl.attachShader(p, shader(gl.VERTEX_SHADER, VS));
    gl.attachShader(p, shader(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS))
      throw new Error(gl.getProgramInfoLog(p) ?? 'link');
    return p;
  }

  private upload(data: Float32Array): WebGLBuffer {
    const b = this.gl.createBuffer();
    if (!b) throw new Error('buffer');
    this.gl.bindBuffer(this.gl.ARRAY_BUFFER, b);
    this.gl.bufferData(this.gl.ARRAY_BUFFER, data, this.gl.STATIC_DRAW);
    return b;
  }

  /** Палитра: синий, белый, золото, VK, OK, MAX, серый (сбой), приглушённый. */
  readPalette(): void {
    const css = getComputedStyle(this.canvas);
    const pal: [number, number, number][] = [
      [0.3, 0.55, 1.0],
      [0.93, 0.95, 1.0],
      [1.0, 0.7, 0.28],
      hexToRgb(css.getPropertyValue('--color-vk'), [0.22, 0.52, 1.0]),
      hexToRgb(css.getPropertyValue('--color-ok'), [1.0, 0.5, 0.2]),
      hexToRgb(css.getPropertyValue('--color-max'), [0.18, 0.86, 0.55]),
      [0.5, 0.53, 0.6],
      [0.36, 0.45, 0.62],
    ];
    if (this.look.light) {
      // На светлом фоне светлые точки теряются — берём тёмные насыщенные цвета
      pal[0] = [0.13, 0.33, 0.8];
      pal[1] = [0.2, 0.25, 0.34];
      pal[2] = [0.82, 0.5, 0.0];
      pal[7] = [0.42, 0.5, 0.62];
    }
    this.palette = new Float32Array(pal.flat());
  }

  /** Новая форма: точки перелетают в неё из текущей. */
  setForm(key: string, build: () => Float32Array, look: SceneLook): void {
    let buf = this.buffers.get(key);
    if (!buf) {
      buf = this.upload(build());
      this.buffers.set(key, buf);
    }
    const themeChanged = look.light !== this.look.light;
    this.look = look;
    if (themeChanged) this.readPalette();
    if (buf === this.toBuf) return;
    this.fromBuf = this.toBuf ?? buf;
    this.toBuf = buf;
    this.morphStart = this.opts.still ? -Infinity : performance.now();
    this.start();
  }

  setVisible(visible: boolean): void {
    this.visible = visible;
    if (visible) this.start();
  }

  private start(): void {
    if (!this.raf) this.raf = requestAnimationFrame((t) => this.frame(t));
  }

  private frame(now: number): void {
    this.raf = 0;
    if (!this.visible || !this.toBuf || !this.fromBuf) return;
    const gl = this.gl;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.round(this.canvas.clientWidth * dpr);
    const h = Math.round(this.canvas.clientHeight * dpr);
    if (w === 0 || h === 0) return; // экран скрыт — рисовать нечего
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    const time = this.opts.still ? 0 : (now - this.t0) / 1000;
    const p = Math.min(1, Math.max(0, (now - this.morphStart) / MORPH_MS));

    gl.viewport(0, 0, w, h);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    // Тёмная тема — свечение сложением яркости; светлая — обычное наложение
    if (this.look.light)
      gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    else gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE, gl.ONE, gl.ONE);

    gl.useProgram(this.program);
    this.bind(this.attr.from, this.fromBuf);
    this.bind(this.attr.to, this.toBuf);
    this.bind(this.attr.rnd, this.rndBuf);
    gl.uniform1f(this.loc.uP ?? null, p);
    gl.uniform1f(this.loc.uTime ?? null, time);
    gl.uniform1f(this.loc.uSpread ?? null, this.opts.still ? 0 : 0.55);
    gl.uniform1f(this.loc.uAspect ?? null, w / h);
    // На светлом фоне свечения нет — точки плотнее и чуть крупнее
    gl.uniform1f(this.loc.uPx ?? null, (this.look.light ? 2.3 : 1.9) * dpr);
    gl.uniform1f(this.loc.uSoft ?? null, this.look.light ? 1.6 : 3.2);
    gl.uniform1f(this.loc.uAngle ?? null, this.look.angle + Math.sin(time * 0.35) * this.look.sway);
    gl.uniform1f(this.loc.uScale ?? null, this.look.scale);
    gl.uniform1f(this.loc.uAlpha ?? null, this.look.light ? 1 : 0.8);
    gl.uniform1f(this.loc.uLight ?? null, this.look.light ? 1 : 0);
    gl.uniform3fv(this.loc.uPal ?? null, this.palette);
    gl.drawArrays(gl.POINTS, 0, this.opts.count);

    // Анимация нужна, пока точки летят, течёт или мерцает; без движения — один кадр
    if (!this.opts.still) this.start();
  }

  private bind(loc: number, buf: WebGLBuffer): void {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 4, gl.FLOAT, false, 0, 0);
  }

  /** Перерисовать один кадр (например, после смены размера без движения). */
  redraw(): void {
    this.start();
  }

  destroy(): void {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    const gl = this.gl;
    for (const b of this.buffers.values()) gl.deleteBuffer(b);
    gl.deleteBuffer(this.rndBuf);
    gl.deleteProgram(this.program);
    gl.getExtension('WEBGL_lose_context')?.loseContext();
  }
}
