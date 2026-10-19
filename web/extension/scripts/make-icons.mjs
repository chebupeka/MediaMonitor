// Значки расширения 16, 32, 48 и 128 px — тот же рисунок, что у фавикона мокапа (web/index.html):
// тёмный скруглённый квадрат и три точки цветов ВКонтакте, Одноклассников и MAX.
// Без зависимостей: рисуем со сглаживанием и сами упаковываем PNG.
// Запуск: `npm run ext:icons` → extension/public/icon/*.png
import { mkdirSync, writeFileSync } from 'node:fs';
import { deflateSync } from 'node:zlib';

const SIZES = [16, 32, 48, 128];
const OUT = new URL('../public/icon/', import.meta.url);

// Рисунок в координатах 32×32, как SVG фавикона
const BG = { color: [0x1c, 0x24, 0x30], radius: 8 };
const DOTS = [
  { x: 11, y: 12, r: 3, color: [0x2a, 0x78, 0xd6] }, // ВКонтакте
  { x: 21, y: 12, r: 3, color: [0xeb, 0x68, 0x34] }, // Одноклассники
  { x: 16, y: 21, r: 3, color: [0x1b, 0xaf, 0x7a] }, // MAX
];

function insideRoundedRect(x, y) {
  const r = BG.radius;
  const cx = Math.min(Math.max(x, r), 32 - r);
  const cy = Math.min(Math.max(y, r), 32 - r);
  return (x - cx) ** 2 + (y - cy) ** 2 <= r * r && x >= 0 && y >= 0 && x <= 32 && y <= 32;
}

function sample(x, y) {
  for (const d of DOTS) if ((x - d.x) ** 2 + (y - d.y) ** 2 <= d.r * d.r) return [...d.color, 255];
  return insideRoundedRect(x, y) ? [...BG.color, 255] : [0, 0, 0, 0];
}

function render(size) {
  const SS = 6; // подвыборок на пиксель по каждой оси
  const scale = 32 / size;
  const rows = [];
  for (let py = 0; py < size; py++) {
    const row = Buffer.alloc(1 + size * 4); // байт фильтра 0 + RGBA
    for (let px = 0; px < size; px++) {
      let r = 0,
        g = 0,
        b = 0,
        a = 0;
      for (let sy = 0; sy < SS; sy++) {
        for (let sx = 0; sx < SS; sx++) {
          const c = sample((px + (sx + 0.5) / SS) * scale, (py + (sy + 0.5) / SS) * scale);
          r += c[0] * c[3];
          g += c[1] * c[3];
          b += c[2] * c[3];
          a += c[3];
        }
      }
      const o = 1 + px * 4;
      if (a > 0) {
        row[o] = Math.round(r / a);
        row[o + 1] = Math.round(g / a);
        row[o + 2] = Math.round(b / a);
      }
      row[o + 3] = Math.round(a / (SS * SS));
    }
    rows.push(row);
  }
  return png(size, Buffer.concat(rows));
}

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(buf) {
  let c = 0xffffffff;
  for (const byte of buf) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

function png(size, raw) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // бит на канал
  ihdr[9] = 6; // RGBA
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

mkdirSync(OUT, { recursive: true });
for (const size of SIZES) writeFileSync(new URL(`${size}.png`, OUT), render(size));
console.log(`Значки: ${SIZES.join(', ')} px → extension/public/icon/`);
