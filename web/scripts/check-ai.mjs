// npm run check:ai — одинаковость результата проверки текста на ИИ (тест-раннера в web/ нет).
// Грузит src/api/fake/ai-selftest.ts через Vite (те же псевдонимы @/, что у мокапа), запускает
// проверки и сверяет тест-векторы нормализации ещё и с node:crypto. Код выхода 1 — есть нарушения.
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const root = fileURLToPath(new URL('..', import.meta.url));

const server = await createServer({
  root,
  configFile: fileURLToPath(new URL('../vite.config.ts', import.meta.url)),
  logLevel: 'error',
  appType: 'custom',
  server: { middlewareMode: true, hmr: false, ws: false },
  optimizeDeps: { noDiscovery: true, include: [] },
});

let failed = false;
try {
  const normalize = await server.ssrLoadModule('/src/lib/ai-normalize.ts');
  for (const v of normalize.AI_NORMALIZE_VECTORS) {
    const hex = createHash('sha256').update(v.normalized, 'utf8').digest('hex');
    if (hex !== v.sha256) {
      failed = true;
      console.error(`node:crypto: SHA-256 вектора «${v.note}» не совпал`);
    }
  }

  const { runAiSelfTest } = await server.ssrLoadModule('/src/api/fake/ai-selftest.ts');
  const { failures, lines } = await runAiSelfTest();
  for (const line of lines) process.stdout.write(`${line}\n`);
  for (const failure of failures) console.error(`НАРУШЕНИЕ: ${failure}`);
  if (failures.length > 0) failed = true;
} catch (error) {
  failed = true;
  console.error(error);
} finally {
  await server.close();
}

process.stdout.write(failed ? 'check:ai — ЕСТЬ НАРУШЕНИЯ\n' : 'check:ai — всё совпадает\n');
process.exit(failed ? 1 : 0);
