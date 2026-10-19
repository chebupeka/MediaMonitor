// JSON Schema контракта из web/src/api/types.ts.
// Результат: server/tests/contract/contract.schema.json — по нему тесты сервера
// проверяют каждый ответ API (лишние и недостающие поля — ошибка).
// Запуск: cd server/scripts/contract && npm install && npm run schema
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createGenerator } from 'ts-json-schema-generator';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '../../..');
const typesPath = resolve(repo, 'web/src/api/types.ts');
const out = resolve(repo, 'server/tests/contract/contract.schema.json');

// SearchRun — объект с методами (поток событий в браузере), по HTTP не передаётся:
// по сети идут сами события SearchEvent. ExportFile — файл (Blob) в браузере: по сети идёт
// телом ответа `export.xlsx`, имя — в Content-Disposition, число строк — в X-Export-Rows.
const SKIP = new Set(['SearchRun', 'ExportFile']);
const source = readFileSync(typesPath, 'utf8');
const names = [...source.matchAll(/^export (?:interface|type) (\w+)/gmu)]
  .map((m) => m[1])
  .filter((name) => !SKIP.has(name));

const generator = createGenerator({
  path: typesPath,
  expose: 'export',
  topRef: true,
  skipTypeCheck: true,
  additionalProperties: false,
  functions: 'hide',
  jsDoc: 'none',
  sortProps: true,
});

const definitions = {};
for (const name of names) {
  const schema = generator.createSchema(name);
  Object.assign(definitions, schema.definitions ?? {});
}
const sorted = Object.fromEntries(Object.keys(definitions).sort().map((k) => [k, definitions[k]]));
const result = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  $comment: 'Сгенерировано из web/src/api/types.ts (server/scripts/contract/gen-schema.mjs). Не править руками.',
  definitions: sorted,
};
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
console.log(`JSON Schema: ${Object.keys(sorted).length} типов → ${out}`);
