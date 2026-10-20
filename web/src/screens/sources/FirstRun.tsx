/**
 * Первый запуск (НТ-14, SC-30): список пуст. Объясняем, что режим «Везде» работает без
 * списка, и предлагаем готовый каталог краевых источников — одним действием.
 */
import { ArrowRight, FileSpreadsheet, Library, Link2 } from 'lucide-react';
import { useCallback, type CSSProperties } from 'react';
import { api, useAsync } from '@/api';
import type { PlatformId } from '@/api/types';
import { Button, cx, PlatformDot } from '@/components';
import { DotsStage } from '@/dots';
import { formatCount, plural, WORDS } from '@/lib/format';
import { PLATFORM_ORDER, PLATFORMS } from '@/lib/labels';
import styles from './sources.module.css';

export function FirstRun({
  onCatalog,
  onAdd,
  onImport,
  onSearch,
}: {
  onCatalog: () => void;
  onAdd: () => void;
  onImport: () => void;
  onSearch: () => void;
}) {
  const catalog = useAsync(useCallback(() => api.getCatalog(), []));
  const size = catalog.data?.length ?? null;
  const by = (p: PlatformId): number => catalog.data?.filter((c) => c.platform === p).length ?? 0;

  return (
    <div className={styles.firstRun}>
      {/* Карта края крупно, во всю ширину — как первый экран сайта */}
      <div className={styles.firstScene}>
        <DotsStage
          form="krai"
          intensity="calm"
          captionAlign="center"
          caption="Красноярский край — в режиме «Везде» поиск идёт по всему краю, список не нужен."
        />
      </div>

      <header className={styles.firstHead}>
        <h2 className={styles.firstTitle}>Список пока пуст</h2>
        <p className={styles.firstLead}>
          Искать можно уже сейчас. Свой список нужен только для режима «Мои источники» — когда
          важно, что пишут именно выбранные группы и каналы.
        </p>
      </header>

      <div className={cx(styles.region, styles.reveal)}>
        <span className={styles.regionDot} aria-hidden="true" />
        <div className={styles.regionText}>
          <p>
            <b>Режим «Везде» работает без списка.</b> Ищем публичные посты Красноярского края во
            ВКонтакте, Одноклассниках и MAX. Пост краевой, если его опубликовал краевой источник или
            в тексте упоминается место края.
          </p>
          <p>
            Во ВКонтакте поиска по всей площадке для нас нет — там обходим широкий пул сообществ
            края, и над подборкой так и пишем: «VK: поиск по N сообществам края».
          </p>
          <div>
            <Button size="sm" iconEnd={<ArrowRight />} onClick={onSearch}>
              Искать везде без списка
            </Button>
          </div>
        </div>
      </div>

      <div className={styles.firstTiles}>
        <section
          className={cx(styles.tile, styles.reveal)}
          style={{ '--i': 1 } as CSSProperties}
          aria-labelledby="first-catalog"
        >
          <h3 id="first-catalog" className={styles.tileLabel}>
            Готовый каталог края
          </h3>
          <span className={styles.tileNum}>{size ?? '—'}</span>
          <span className={styles.tileNote}>
            {size === null
              ? 'Загружаем каталог…'
              : `${plural(size, WORDS.source)}: краевые и районные СМИ, органы власти, администрации, сообщества городов`}
          </span>
          {catalog.data && (
            <ul className={styles.platformRows} aria-label="Каталог по площадкам">
              {PLATFORM_ORDER.map((p) => (
                <li key={p}>
                  <span className={styles.platformRowName}>
                    <PlatformDot platform={p} size="sm" />
                    {PLATFORMS[p].name}
                  </span>
                  <b>{by(p)}</b>
                </li>
              ))}
            </ul>
          )}
          <Button
            variant="primary"
            iconStart={<Library />}
            onClick={onCatalog}
            className={styles.wrapButton}
          >
            {size === null
              ? 'Добавить каталог края'
              : `Добавить каталог · ${formatCount(size, WORDS.source)}`}
          </Button>
        </section>

        <section
          className={cx(styles.tile, styles.reveal)}
          style={{ '--i': 2 } as CSSProperties}
          aria-labelledby="first-own"
        >
          <h3 id="first-own" className={styles.tileLabel}>
            Свой список
          </h3>
          <ul className={styles.ways}>
            <li>
              <p className={styles.wayTitle}>
                <Link2 aria-hidden="true" />
                По ссылке
              </p>
              <p className={styles.tileNote}>
                Вставьте адрес группы или канала — сразу проверим, открыта ли она и сколько у неё
                подписчиков.
              </p>
              <div>
                <Button size="sm" onClick={onAdd}>
                  Добавить по ссылке
                </Button>
              </div>
            </li>
            <li>
              <p className={styles.wayTitle}>
                <FileSpreadsheet aria-hidden="true" />
                Из Excel
              </p>
              <p className={styles.tileNote}>
                Таблица со ссылками в одной колонке. После загрузки покажем, что вошло и что нет.
              </p>
              <div>
                <Button size="sm" onClick={onImport}>
                  Загрузить файл
                </Button>
              </div>
            </li>
          </ul>
        </section>
      </div>
    </div>
  );
}
