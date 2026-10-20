// Сжать сайт и веб-версию заранее: рядом с каждым текстовым файлом — .br (brotli, качество 11)
// и .gz (gzip 9), если они заметно меньше. Сервер (src/mediamonitor/api/static.py) отдаёт
// готовый вариант по Accept-Encoding и не тратит процессор на сжатие при каждом запросе.
//
//   node scripts/precompress.mjs <папка> [<папка> …]      (запускает Dockerfile)
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { extname, join } from 'node:path';
import { brotliCompressSync, constants, gzipSync } from 'node:zlib';

const TEXT = new Set([
  '.html', '.htm', '.css', '.js', '.mjs', '.json', '.map', '.svg', '.txt', '.xml',
  '.webmanifest', '.ttf', '.otf', '.wasm',
]);
const MIN_BYTES = 256;
const WORTH = 0.95; // вариант нужен, только если он хотя бы на 5% меньше

function* walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(path);
    else if (entry.isFile()) yield path;
  }
}

let files = 0;
let plain = 0;
let packed = 0;
for (const root of process.argv.slice(2)) {
  for (const file of walk(root)) {
    if (!TEXT.has(extname(file).toLowerCase())) continue;
    const body = readFileSync(file);
    if (body.length < MIN_BYTES) continue;
    const br = brotliCompressSync(body, {
      params: {
        [constants.BROTLI_PARAM_QUALITY]: constants.BROTLI_MAX_QUALITY,
        [constants.BROTLI_PARAM_SIZE_HINT]: body.length,
      },
    });
    const gz = gzipSync(body, { level: 9 });
    if (br.length < body.length * WORTH) writeFileSync(`${file}.br`, br);
    if (gz.length < body.length * WORTH) writeFileSync(`${file}.gz`, gz);
    files += 1;
    plain += body.length;
    packed += Math.min(br.length, body.length);
  }
}
const kb = (n) => `${Math.round(n / 1024)} КБ`;
console.log(`Сжато файлов: ${files}; ${kb(plain)} → ${kb(packed)} (brotli)`);
