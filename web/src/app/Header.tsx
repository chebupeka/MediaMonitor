import { Check, Menu } from 'lucide-react';
import { DropdownMenu } from 'radix-ui';
import { IS_MOCKUP } from '@/api';
import { DemoBadge, IconButton, cx } from '@/components';
import { IS_WEB_BUILD } from '@/lib/build';
import { useNavigation, type ScreenId } from './navigation';
import { SCREENS, SCREEN_ORDER } from './screens';
import { PrefsButtons } from './PrefsButtons';
import { useShell } from './shell-state';
import styles from './Header.module.css';

/** Знак как на сайте: название узким гротеском капсом и золотая точка — «найденное». */
export function Logo() {
  return (
    <span className={styles.wordmark}>
      <span className={styles.brandName}>Медиарадар</span>
      <span className={styles.brandDot} aria-hidden="true" />
    </span>
  );
}

/**
 * Меню ☰ — как бургер сайта: все разделы (в узкой панели навигации нет) и переключатель
 * «Анимация точек». Тема и версия для слабовидящих — отдельными кнопками рядом (Prefs).
 */
function ScreensMenu({
  screens,
  current,
  onSelect,
  size,
}: {
  screens: ScreenId[];
  current: ScreenId;
  onSelect: (id: ScreenId) => void;
  size: 'sm' | 'md';
}) {
  const { dotsChoice, setDotsEnabled, lowVision } = useShell();
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <IconButton
          label="Разделы"
          icon={<Menu />}
          tooltip={false}
          className={styles.menuButton}
          size={size}
        />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className={styles.menu} align="end" sideOffset={6}>
          {screens.map((id) => (
            <DropdownMenu.Item
              key={id}
              className={cx(styles.menuItem, id === current && styles.menuItemCurrent)}
              onSelect={() => onSelect(id)}
            >
              <span className={styles.indicator}>
                {id === current && <Check aria-hidden="true" />}
              </span>
              {SCREENS[id].navLabel}
            </DropdownMenu.Item>
          ))}
          <DropdownMenu.Separator className={styles.separator} />
          {/* В версии для слабовидящих точек нет вовсе — переключатель не нужен */}
          <DropdownMenu.CheckboxItem
            checked={dotsChoice && !lowVision}
            disabled={lowVision}
            onCheckedChange={(v) => setDotsEnabled(v === true)}
            className={styles.menuItem}
          >
            <DropdownMenu.ItemIndicator className={styles.indicator}>
              <Check aria-hidden="true" />
            </DropdownMenu.ItemIndicator>
            Анимация точек
          </DropdownMenu.CheckboxItem>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export function Header({ compact }: { compact: boolean }) {
  const { screen, navigate } = useNavigation();
  const main = SCREEN_ORDER.filter((id) => SCREENS[id].group === 'main');
  // В веб-версии нет лендинга мокапа («Установить расширение» — на сайте)
  const menuScreens = SCREEN_ORDER.filter(
    (id) => SCREENS[id].group !== 'mock' && !(IS_WEB_BUILD && SCREENS[id].group === 'home'),
  );

  return (
    <header className={cx(styles.header, compact && styles.compact)}>
      <button
        type="button"
        className={styles.brand}
        // Главный экран расширения — «Поиск»; витрина продукта — отдельный сайт
        onClick={() => navigate('search')}
        aria-label="Медиарадар — к поиску"
      >
        <Logo />
      </button>

      {!compact && (
        <nav className={styles.nav} aria-label="Разделы">
          <ul className={styles.navList}>
            {main.map((id) => (
              <li key={id}>
                <button
                  type="button"
                  className={styles.navItem}
                  aria-current={screen === id ? 'page' : undefined}
                  onClick={() => navigate(id)}
                >
                  {SCREENS[id].navLabel}
                </button>
              </li>
            ))}
          </ul>
        </nav>
      )}

      <div className={styles.tools}>
        {/* «Демо-данные» — только на имитации; с сервером данные настоящие */}
        {IS_MOCKUP && <DemoBadge short={compact} />}
        <ScreensMenu
          screens={menuScreens}
          current={screen}
          onSelect={(id) => navigate(id)}
          size={compact ? 'sm' : 'md'}
        />
        <PrefsButtons compact={compact} />
        {/* Выйти из предпросмотра панели — переключатель в панели «Демо-сценарий». */}
      </div>
    </header>
  );
}
