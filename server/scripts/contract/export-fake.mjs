// Выгрузка из имитации web/src/api/fake (web/ только читаем):
//  1) образцы ответов MonitorApi для теста контракта: server/tests/contract/samples/*.json
//     (`npm run export`, режим `samples`);
//  2) фикстуры площадок для FixtureAdapter сервера — «что вернула площадка» по
//     записанным запросам: server/src/mediamonitor/fixtures/*.json (`npm run export:fixtures`).
//
// Фикстуры записаны из прежней имитации (до перехода на ветку интерфейса): в них больше
// постов и сценариев (посты «только из списка», расширенный релиз), чем в наборах ветки,
// и на них опираются тесты сервера. Поэтому обычная выгрузка их не трогает;
// `export:fixtures` перезапишет их наборами текущей имитации.
// Запуск: cd server/scripts/contract && npm install && npm run export
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '../../..');
const web = resolve(repo, 'web');
const fixturesDir = resolve(repo, 'server/src/mediamonitor/fixtures');
const dataDir = resolve(repo, 'server/src/mediamonitor/data');
const samplesDir = resolve(repo, 'server/tests/contract/samples');

const { createServer } = await import(
  pathToFileURL(resolve(web, 'node_modules/vite/dist/node/index.js')).href
);
const vite = await createServer({
  root: web,
  configFile: false,
  // Кэш Vite — во временной папке, чтобы ничего не писать в web/.
  cacheDir: join(tmpdir(), 'mediamonitor-contract-vite'),
  logLevel: 'error',
  appType: 'custom',
  server: { middlewareMode: true, hmr: false, watch: null },
  resolve: { alias: { '@': resolve(web, 'src') } },
});

const load = (path) => vite.ssrLoadModule(path);
const mode = process.argv[2] ?? 'samples';
if (mode !== 'samples' && mode !== 'fixtures') {
  console.error(`Неизвестный режим «${mode}»: samples или fixtures`);
  process.exit(2);
}

try {
  const sources = await load('/src/api/fake/sources.ts');
  const bdd = await load('/src/api/fake/datasets/bdd.ts');
  const release = await load('/src/api/fake/datasets/release.ts');
  const event = await load('/src/api/fake/datasets/event.ts');
  const large = await load('/src/api/fake/datasets/large.ts');

  const write = (dir, name, value) =>
    writeFileSync(join(dir, name), `${JSON.stringify(value, null, 2)}\n`, 'utf8');

  // ------------------------------------------------------------ фикстуры площадок
  if (mode === 'fixtures') {
  const seedOfRef = new Map(sources.SOURCE_SEEDS.map((s) => [s.id, s]));
  const rawPost = (demo) => {
    const p = demo.item.publication;
    const seed = seedOfRef.get(p.source.id);
    return {
      platform: p.platform,
      ownerId: p.key.ownerId,
      postId: p.key.postId,
      sourceId: p.source.id,
      title: p.title,
      text: p.text,
      publishedAt: p.publishedAt,
      timeReliability: p.timeReliability,
      edited: p.edited,
      repostOf: p.repostOf,
      hasMedia: p.hasMedia,
      views: p.views,
      reactions: p.reactions,
      altUrls: p.mergedUrls,
      sourceSlug: seed?.slug ?? null,
    };
  };
  const postsOf = (dataset, withOptional = true) => {
    const list = [...dataset.items, ...(withOptional ? dataset.optional.flatMap((o) => o.items) : [])];
    const seen = new Set();
    return list.map(rawPost).filter((p) => {
      const key = `${p.platform}:${p.ownerId}_${p.postId}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  };

  // Посты некраевых источников без упоминания края (п. 48): площадка отдаёт их только в
  // режиме «Мои источники», если источник в списке пользователя.
  const listOnlyOf = (dataset) => (dataset.listOnly ?? []).map(rawPost);
  mkdirSync(fixturesDir, { recursive: true });
  const NOTE =
    'Записанные примеры для FixtureAdapter (режим разработки и тестов). Источники вымышлены, ' +
    'ссылки построены по формату площадок и ведут на несуществующие посты. Сгенерировано ' +
    'server/scripts/contract/export-fake.mjs из web/src/api/fake/datasets — не править руками.';

  write(fixturesDir, 'sources.json', {
    $comment: NOTE,
    sources: sources.SOURCE_SEEDS.map((s) => ({
      id: s.id,
      platform: s.platform,
      name: s.name,
      slug: s.slug,
      ownerId: s.ownerId,
      type: s.type,
      district: s.district,
      subscribers: s.subscribers,
      regional: s.regional,
      closed: s.closed ?? false,
      description: s.description,
    })),
    everywherePool: sources.EVERYWHERE_POOL,
  });

  const bddSet = bdd.buildBdd();
  const releaseSet = release.buildRelease();
  const largeSet = large.buildLarge();
  const recordings = [
    {
      id: 'release',
      $comment: 'Текст релиза «Новая школа в Норильске» или его кусок (совпали ≥ 2 фразы из трёх слов).',
      match: {
        regex: ['школ[\\s\\S]*норильск', 'норильск[\\s\\S]*школ'],
        shingleTexts: [release.RELEASE_SOURCE_TEXT, ...postsOf(releaseSet).map((p) => p.text ?? '')],
        minShingleHits: 2,
        meaningId: null,
      },
      posts: postsOf(releaseSet),
      listOnly: listOnlyOf(releaseSet),
    },
    {
      id: 'bdd',
      $comment: 'Тема «Безопасность дорожного движения» и близкие слова.',
      match: {
        regex: ['(бдд|дтп|дорожн|пешеход|водител|светофор|автомобил|гололёд|гололед|госавтоинспекц|гибдд)'],
        shingleTexts: [],
        minShingleHits: 0,
        meaningId: null,
      },
      posts: postsOf(bddSet),
      listOnly: listOnlyOf(bddSet),
    },
    ...['river', 'club', 'all'].map((meaningId) => ({
      id: `event-${meaningId}`,
      $comment: `Событие «Енисей», значение: ${meaningId}.`,
      match: {
        regex: ['(енисе|ледостав|навигаци|северн\\w*\\s+завоз)'],
        shingleTexts: [],
        minShingleHits: 0,
        meaningId,
      },
      posts: postsOf(event.buildEvent(meaningId)),
      listOnly: listOnlyOf(event.buildEvent(meaningId)),
    })),
    {
      id: 'large',
      $comment: 'Нагрузочный набор: 500 публикаций по теме БДД (К26, SC-16). Только для тестов.',
      match: {
        regex: ['^нагрузочный набор 500$'],
        shingleTexts: [],
        minShingleHits: 0,
        meaningId: null,
      },
      posts: postsOf(largeSet),
      listOnly: listOnlyOf(largeSet),
    },
  ];
  write(fixturesDir, 'recordings.json', { $comment: NOTE, recordings });
  // Посты вне выдачи поиска: их можно получить только по ссылке (П8, «добавить по ссылке»).
  const spare = [bddSet, releaseSet].flatMap((set) => set.spare.map(rawPost));
  write(fixturesDir, 'extra-posts.json', { $comment: NOTE, posts: spare });
  mkdirSync(dataDir, { recursive: true });
  write(dataDir, 'ambiguous.json', {
    $comment:
      'Многозначные запросы (П14): какие значения предлагаем уточнить. Сгенерировано из event.ts.',
    terms: [
      {
        pattern: '^\\s*енисей\\s*$',
        question: 'Уточните, что ищем: «Енисей» — это и река, и спортивный клуб.',
        options: event.EVENT_MEANINGS.map((m) => ({ id: m.id, label: m.label, description: m.description })),
      },
    ],
  });
  console.log(`Фикстуры: ${recordings.length} записей, ${spare.length} постов по ссылке → ${fixturesDir}`);
  }

  // ------------------------------------------------------------ образцы ответов имитации
  if (mode === 'samples') {

  const fake = await load('/src/api/fake/index.ts');
  const scenario = await load('/src/api/fake/scenario.ts');
  const clock = await load('/src/api/fake/clock.ts');
  const api = fake.createFakeApi();
  const samples = [];
  const keep = (name, schema, value) => samples.push({ name, schema, value });
  const collect = async (run) => {
    const events = [];
    for await (const e of run) events.push(e);
    return events;
  };
  // Поток событий целиком, но списки записей в нём урезаны: разнообразие полей
  // уже есть в полной подборке getSelection, а форма событий от этого не меняется.
  const trimEvent = (e) => {
    if (e.type === 'items') return { ...e, items: e.items.slice(0, 3) };
    if (e.type === 'finished' || e.type === 'stopped')
      return { ...e, selection: { ...e.selection, items: e.selection.items.slice(0, 3) } };
    return e;
  };
  const keepEvents = (name, events) => keep(name, 'SearchEvent[]', events.map(trimEvent));
  const period30 = { preset: '30d', from: clock.addDays(clock.krskDate(clock.demoNowMs()), -29), to: clock.krskDate(clock.demoNowMs()) };

  keep('getStartState', 'StartState', await api.getStartState());
  keep('analyzeQuery-hints', 'QueryAnalysis', await api.analyzeQuery(fake.DEMO_QUERIES[4].text));
  keep('analyzeQuery-ambiguous', 'QueryAnalysis', await api.analyzeQuery('Енисей'));
  keep('analyzeQuery-link', 'QueryAnalysis', await api.analyzeQuery(fake.DEMO_QUERIES[5].text));
  keep('understandTopic', 'TopicUnderstanding', await api.understandTopic('Безопасность дорожного движения'));
  keep(
    'understandTopic-corrected',
    'TopicUnderstanding',
    await api.understandTopic('Безопасность дорожного движения', {
      correction: { include: ['fire'], exclude: [], notes: 'без ремонта дорог' },
    }),
  );

  const bddRun = api.startSearch({ text: 'Безопасность дорожного движения', period: period30, mode: 'everywhere' });
  keepEvents('event-bdd', await collect(bddRun));
  const sel = await api.getSelection(bddRun.searchId);
  keep('getSelection', 'Selection', sel);
  const first = sel.items[0];
  keep('setExcluded', 'SelectionCounts', await api.setExcluded(bddRun.searchId, [first.id], true));
  keep('excludeSource', null, await api.excludeSource(bddRun.searchId, sel.items[1].publication.source.id));
  keep('addByUrl', 'ResultItem', await api.addByUrl(bddRun.searchId, fake.DEMO_LINKS.addByUrl));
  keep('recheckLinks', 'LinkRecheckReport', await api.recheckLinks(bddRun.searchId));
  keep('getExportPreview', 'ExportPreview', await api.getExportPreview(bddRun.searchId));
  keep(
    'getExportPreview-filtered',
    'ExportPreview',
    await api.getExportPreview(bddRun.searchId, { onlyRelevance: ['direct', 'disputed'] }),
  );

  const releaseRun = api.startSearch({ text: release.RELEASE_SOURCE_TEXT, period: period30, mode: 'everywhere' });
  keepEvents('event-release', await collect(releaseRun));
  keep('getSpread', 'SpreadReport', await api.getSpread(releaseRun.searchId));

  const stopRun = api.startSearch({ text: 'Енисей', period: period30, mode: 'everywhere', meaningId: 'river' });
  setTimeout(() => stopRun.stop(), 900);
  keepEvents('event-stop', await collect(stopRun));

  scenario.setDemoState({ scenario: 'max-down', maxFailure: 'unavailable' });
  const failRun = api.startSearch({ text: 'ДТП', period: period30, mode: 'everywhere' });
  keepEvents('event-maxdown', await collect(failRun));
  keepEvents('event-retry', await collect(api.retryPlatform(failRun.searchId, 'max')));
  scenario.setDemoState({ scenario: 'ai-down' });
  keepEvents('event-aidown', await collect(api.startSearch({ text: 'ДТП', period: period30, mode: 'everywhere' })));
  scenario.setDemoState({ scenario: 'queue' });
  keepEvents('event-queue', await collect(api.startSearch({ text: 'ДТП', period: period30, mode: 'everywhere' })));
  scenario.setDemoState({ scenario: 'normal' });
  keepEvents(
    'event-failed',
    await collect(api.startSearch({ text: 'а'.repeat(20_001), period: period30, mode: 'everywhere' })),
  );

  keep('listSources', 'Source[]', await api.listSources());
  for (const [name, url] of Object.entries(fake.DEMO_LINKS)) {
    if (name === 'addByUrl') continue;
    keep(`checkSource-${name}`, 'SourceCheck', await api.checkSource(url));
  }
  const added = await api.addSource({ url: fake.DEMO_LINKS.sourceOk });
  keep('addSource', 'Source', added);
  keep('updateSource', 'Source', await api.updateSource(added.id, { name: 'Минусинск', district: null }));
  await api.removeSource(added.id);
  keep('restoreSource', 'Source', await api.restoreSource(added.id));
  keep('recheckSources', 'SourcesRecheckReport', await api.recheckSources());
  const preview = await api.previewImport(new File(['demo'], 'источники.xlsx'));
  keep('previewImport', 'ImportPreview', preview);
  keep('importSources', 'ImportReport', await api.importSources(preview.previewId));
  const catalog = await api.getCatalog();
  keep('getCatalog', 'CatalogSource[]', catalog);
  keep('addFromCatalog', 'Source[]', await api.addFromCatalog(catalog.filter((c) => !c.inMySources).slice(0, 1).map((c) => c.id)));
  keep('getWorkspace', 'Workspace', await api.getWorkspace());
  const link = await api.getWorkspaceLink();
  keep('getWorkspaceLink', 'WorkspaceLink', link);
  keep('openWorkspace', 'Workspace', await api.openWorkspace(link.key));
  keep('listRecent', 'RecentSearch[]', await api.listRecent());
  keep('getStandStatus', 'StandStatus', await api.getStandStatus());
  try {
    await api.getSelection('no-such-search');
  } catch (error) {
    keep('error-not-found', 'ApiError', { code: error.code, message: error.message });
  }

  rmSync(samplesDir, { recursive: true, force: true });
  mkdirSync(samplesDir, { recursive: true });
  for (const sample of samples) {
    write(samplesDir, `${sample.name}.json`, { method: sample.name, schema: sample.schema, value: sample.value });
  }
  console.log(`Образцы имитации: ${samples.length} → ${samplesDir}`);
  }
} finally {
  await vite.close();
}
process.exit(0);
