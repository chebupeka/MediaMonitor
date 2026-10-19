/**
 * Оболочка приложения: шапка, экраны, подвал, баннер связи, панель «Демо-сценарий».
 * Две раскладки: сайт и предпросмотр боковой панели расширения (380 px).
 * Посещённые экраны остаются в памяти (скрыты), поэтому поиск не теряется при
 * переходе в «Источники» и обратно. При смене демо-сценария экраны загружаются заново.
 */
import { WifiOff } from 'lucide-react';
import { useEffect, useRef, useState, type ComponentType } from 'react';
import { useConnection } from '@/api';
import { subscribeDemo } from '@/api/fake/scenario';
import { useAnnounce } from '@/components';
import { TIME_ZONE_LABEL_FULL } from '@/lib/format';
import { DemoPanel } from './DemoPanel';
import { Header } from './Header';
import { useNavigation, type ScreenId, type ScreenParamsMap, type ScreenProps } from './navigation';
import { HostPage, SCREENS, SCREEN_COMPONENTS, SCREEN_ORDER } from './screens';
import { useShell } from './shell-state';
import styles from './Shell.module.css';

interface Mounted {
  params: ScreenParamsMap[ScreenId];
  navKey: number;
}

function ConnectionBanner() {
  const connection = useConnection();
  if (connection === 'online') return null;
  return (
    <div className={styles.offline} role="status">
      <WifiOff aria-hidden="true" className={styles.offlineIcon} />
      <span>
        <strong>Нет связи с интернетом.</strong> Поиск продолжается на сервере — найденное не
        потеряется и появится, когда связь вернётся.
      </span>
    </div>
  );
}

function Footer() {
  const { navigate } = useNavigation();
  return (
    <footer className={styles.footer}>
      <div className={styles.footerInfo}>
        <p className={styles.footerText}>
          Медиамонитор · ВКонтакте, Одноклассники и MAX · Красноярский край · только публичные посты
        </p>
        <p className={styles.footerText}>Время везде — {TIME_ZONE_LABEL_FULL}</p>
      </div>
      <nav className={styles.footerNav} aria-label="Служебные страницы">
        <button type="button" className={styles.footerLink} onClick={() => navigate('how')}>
          Как это работает
        </button>
        <button type="button" className={styles.footerLink} onClick={() => navigate('status')}>
          Состояние стенда
        </button>
        <button type="button" className={styles.footerLink} onClick={() => navigate('demo-page')}>
          Демо-страница СМИ
        </button>
      </nav>
    </footer>
  );
}

function renderScreen<S extends ScreenId>(id: S, mounted: Mounted, active: boolean) {
  const Component: ComponentType<ScreenProps<S>> = SCREEN_COMPONENTS[id];
  return (
    <Component
      params={mounted.params as ScreenParamsMap[S]}
      navKey={mounted.navKey}
      active={active}
    />
  );
}

export function Shell() {
  const { layout } = useShell();
  const nav = useNavigation();
  const announce = useAnnounce();
  const mainRef = useRef<HTMLElement>(null);
  const firstRender = useRef(true);
  const [resetKey, setResetKey] = useState(0);
  const [mounted, setMounted] = useState<Partial<Record<ScreenId, Mounted>>>({
    [nav.screen]: { params: nav.params, navKey: nav.navKey },
  });

  // Новый переход: запомнить параметры экрана (производное состояние, без эффекта).
  if (mounted[nav.screen]?.navKey !== nav.navKey) {
    setMounted((m) => ({ ...m, [nav.screen]: { params: nav.params, navKey: nav.navKey } }));
  }

  // Смена демо-сценария: экраны загружаются заново и читают новое состояние имитации.
  useEffect(
    () =>
      subscribeDemo((next, prev) => {
        if (next.scenario === prev.scenario && next.maxFailure === prev.maxFailure) return;
        setResetKey((k) => k + 1);
        setMounted((m) => {
          const current = Object.entries(m).find(([id]) => id === nav.screen);
          return current ? { [nav.screen]: current[1] } : {};
        });
      }),
    [nav.screen],
  );

  // Заголовок окна, фокус и объявление при переходе (доступность).
  useEffect(() => {
    const meta = SCREENS[nav.screen];
    document.title =
      nav.screen === 'landing' ? 'Медиамонитор — мокап' : `${meta.title} — Медиамонитор`;
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    mainRef.current?.focus({ preventScroll: true });
    if (layout === 'site') window.scrollTo({ top: 0 });
    else mainRef.current?.parentElement?.scrollTo({ top: 0 });
    announce(`Открыт раздел: ${meta.title}`);
  }, [nav.navKey, nav.screen, layout, announce]);

  const screens = SCREEN_ORDER.filter((id) => mounted[id] !== undefined);

  return (
    <div className={layout === 'panel' ? styles.panelLayout : styles.siteLayout}>
      {layout === 'panel' ? (
        <div className={styles.host} aria-label="Страница сайта, рядом с которой открыта панель">
          <HostPage />
        </div>
      ) : null}
      <div className={layout === 'panel' ? styles.panelFrame : styles.siteFrame}>
        <button type="button" className={styles.skip} onClick={() => mainRef.current?.focus()}>
          К содержимому
        </button>
        <Header compact={layout === 'panel'} />
        <ConnectionBanner />
        <main id="main" ref={mainRef} tabIndex={-1} className={styles.main}>
          <div key={resetKey} className={styles.screens}>
            {screens.map((id) => {
              const entry = mounted[id];
              if (!entry) return null;
              const active = id === nav.screen;
              return (
                <div key={id} hidden={!active} className={styles.screen} data-screen={id}>
                  {renderScreen(id, entry, active)}
                </div>
              );
            })}
          </div>
        </main>
        {layout === 'site' ? <Footer /> : null}
      </div>
      <DemoPanel />
    </div>
  );
}
