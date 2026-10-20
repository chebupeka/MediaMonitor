// npm run check:web — проверки веб-версии без браузера (тест-раннера в web/ нет, как и для
// check:ai). Модули грузятся через Vite в режиме `web` — те же псевдонимы и VITE_TARGET=web, что
// у `npm run build:web`. Код выхода 1 — есть нарушения.
//
// Что проверяется:
// - причина ошибки запуска поиска не теряется (аудит, О1): `toApiError(new MonitorApiError(…))`
//   сохраняет текст, лимит и id идущего поиска;
// - адреса разделов (Р-В4): путь → экран и обратно, `?search=` у «Распространения»,
//   неизвестный путь — «Такого раздела нет», экраны мокапа по адресу не открываются;
// - ключ рабочего места из ссылки и из ключа как есть;
// - метка группы копий в карточке: «копия · N» / «оригинал · N», у релиза и без группы — нет.
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const root = fileURLToPath(new URL('..', import.meta.url));

const server = await createServer({
  root,
  mode: 'web',
  configFile: fileURLToPath(new URL('../vite.config.ts', import.meta.url)),
  logLevel: 'error',
  appType: 'custom',
  server: { middlewareMode: true, hmr: false, ws: false },
  optimizeDeps: { noDiscovery: true, include: [] },
});

const failures = [];
let passed = 0;
function check(name, ok, details = '') {
  if (ok) passed += 1;
  else failures.push(`${name}${details ? `: ${details}` : ''}`);
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

try {
  // ---------------------------------------------------------------- ошибки (О1)
  const { MonitorApiError, plainApiError } = await server.ssrLoadModule('/src/api/client.ts');
  const { toApiError } = await server.ssrLoadModule('/src/api/http-run.ts');

  const busy = new MonitorApiError('too-many-requests', 'Уже идёт поиск «БДД».', 10, 's-1');
  check(
    'у MonitorApiError текст не перечисляется (поэтому {...e} его теряет)',
    !('message' in { ...busy }),
  );
  const plain = toApiError(busy);
  check(
    'toApiError сохраняет текст',
    plain.message === 'Уже идёт поиск «БДД».',
    JSON.stringify(plain),
  );
  check('toApiError сохраняет код', plain.code === 'too-many-requests');
  check('toApiError сохраняет Retry-After', plain.retryAfterSec === 10);
  check('toApiError сохраняет id идущего поиска', plain.runningSearchId === 's-1');
  const long = toApiError(new MonitorApiError('too-long', 'Текст длиннее 20 000 знаков.'));
  check(
    'без необязательных полей — только код и текст',
    same(long, { code: 'too-long', message: 'Текст длиннее 20 000 знаков.' }),
    JSON.stringify(long),
  );
  check('простой объект ошибки проходит как есть', same(plainApiError(long), long));
  const unknown = toApiError(new TypeError('сеть'));
  check('чужая ошибка — понятный текст', unknown.code === 'server' && unknown.message.length > 10);

  // ---------------------------------------------------------------- адреса (Р-В4)
  const { routeFromLocation, urlFor, URL_ROUTING } =
    await server.ssrLoadModule('/src/app/routes.ts');
  check('в веб-версии экран синхронизирован с адресом', URL_ROUTING === true);
  const at = (pathname, search = '') => routeFromLocation({ pathname, search });
  check('/app/ — Поиск', same(at('/app/'), { screen: 'search', params: {} }));
  check('/app — Поиск', at('/app').screen === 'search');
  check('/app/index.html — Поиск', at('/app/index.html').screen === 'search');
  check('/app/sources — Источники', at('/app/sources').screen === 'sources');
  check('/app/recent/ — Недавние', at('/app/recent/').screen === 'recent');
  check(
    '«Распространение» с поиском и группой',
    same(at('/app/spread', '?search=s-9&group=g-2'), {
      screen: 'spread',
      params: { searchId: 's-9', groupId: 'g-2' },
    }),
  );
  check('неизвестный раздел', at('/app/nope').screen === 'not-found');
  check('лендинг мокапа по адресу не открывается', at('/app/landing').screen === 'not-found');
  check('демо-страница по адресу не открывается', at('/app/demo-page').screen === 'not-found');
  check('чужой путь', at('/other/').screen === 'not-found');
  check('адрес Поиска', urlFor('search', { text: 'дтп', autoRun: true }) === '/app/');
  check('текст запроса в адрес не попадает', !urlFor('search', { text: 'дтп' }).includes('дтп'));
  check('адрес Источников', urlFor('sources', {}) === '/app/sources');
  check(
    'адрес Распространения',
    urlFor('spread', { searchId: 's-9', groupId: 'g-2' }) === '/app/spread?search=s-9&group=g-2',
  );
  for (const screen of ['search', 'spread', 'ai-check', 'sources', 'recent', 'how', 'status']) {
    const url = new URL(urlFor(screen, {}), 'http://x');
    check(`туда и обратно: ${screen}`, at(url.pathname, url.search).screen === screen);
  }

  // ---------------------------------------------------------------- ключ рабочего места
  const { cleanWorkspaceKey } = await server.ssrLoadModule('/src/api/http.ts');
  check('ключ из ссылки', cleanWorkspaceKey('http://h/app/#workspace=abc_D-1') === 'abc_D-1');
  check('ключ как есть', cleanWorkspaceKey('  abc  ') === 'abc');
  check('ключ без хвоста', cleanWorkspaceKey('#workspace=abc&x=1') === 'abc');

  // ---------------------------------------------------------------- имитации нет в веб-версии (Ж7)
  const mock = await server.ssrLoadModule('@/api/mock');
  check(
    'вместо имитации — заглушка: демо-запросов нет',
    mock.demoQueries === undefined && mock.DEMO_QUERIES.length === 0,
  );
  check(
    'имитацию в веб-версии не создать',
    (() => {
      try {
        mock.createFakeApi();
        return false;
      } catch {
        return true;
      }
    })(),
  );
  const shell = await server.ssrLoadModule('@/app/mock-only');
  check('панели «Демо-сценарий» нет', shell.DemoPanel() === null);

  // ---------------------------------------------------------------- группа копий в карточке (Р9)
  const labels = await server.ssrLoadModule('/src/lib/labels.ts');
  const groups = [
    {
      id: 'g-1',
      title: '«Мост» — копии',
      kind: 'copies',
      itemIds: ['a', 'b', 'c'],
      originalItemId: 'a',
    },
    { id: 'g-2', title: 'Релиз', kind: 'release', itemIds: ['r1', 'r2'], originalItemId: 'r1' },
  ];
  const mark = (id, groupId, isOriginal = false) =>
    labels.copyMark({ id, groupId, isOriginal }, groups);
  check('копия в группе копий — «копия · 3»', mark('b', 'g-1')?.label === 'копия · 3');
  check('первая публикация группы — «оригинал · 3»', mark('a', 'g-1')?.label === 'оригинал · 3');
  check(
    'без группы и в группе релиза — без метки',
    mark('x', null) === null && mark('r2', 'g-2') === null,
  );
} catch (error) {
  failures.push(String(error?.stack ?? error));
} finally {
  await server.close();
}

for (const failure of failures) console.error(`НАРУШЕНИЕ: ${failure}`);
process.stdout.write(
  failures.length > 0
    ? `check:web — ЕСТЬ НАРУШЕНИЯ (${failures.length}), выполнено ${passed}\n`
    : `check:web — всё верно: ${passed} проверок\n`,
);
process.exit(failures.length > 0 ? 1 : 0);
