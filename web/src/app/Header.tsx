import { Check, Menu, SunMoon } from 'lucide-react';
import { DropdownMenu } from 'radix-ui';
import { DemoBadge, IconButton, cx } from '@/components';
import { useNavigation, type ScreenId } from './navigation';
import { SCREENS, SCREEN_ORDER } from './screens';
import { useShell, type ThemeChoice } from './shell-state';
import styles from './Header.module.css';

/** Знак: три точки цветов площадок. */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className={styles.logo}>
      <rect width="32" height="32" rx="8" className={styles.logoBg} />
      <circle cx="11" cy="12" r="3.2" fill="var(--color-vk)" />
      <circle cx="21" cy="12" r="3.2" fill="var(--color-ok)" />
      <circle cx="16" cy="21" r="3.2" fill="var(--color-max)" />
    </svg>
  );
}

const THEMES: { value: ThemeChoice; label: string }[] = [
  { value: 'system', label: 'Как в системе' },
  { value: 'light', label: 'Светлая' },
  { value: 'dark', label: 'Тёмная' },
];

function ViewMenu({ size }: { size: 'sm' | 'md' }) {
  const { theme, setTheme, dotsEnabled, setDotsEnabled } = useShell();
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <IconButton label="Вид: тема и анимация" icon={<SunMoon />} tooltip={false} size={size} />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className={styles.menu} align="end" sideOffset={6}>
          <DropdownMenu.Label className={styles.menuLabel}>Тема</DropdownMenu.Label>
          <DropdownMenu.RadioGroup value={theme} onValueChange={(v) => setTheme(v as ThemeChoice)}>
            {THEMES.map((t) => (
              <DropdownMenu.RadioItem key={t.value} value={t.value} className={styles.menuItem}>
                <DropdownMenu.ItemIndicator className={styles.indicator}>
                  <Check aria-hidden="true" />
                </DropdownMenu.ItemIndicator>
                {t.label}
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>
          <DropdownMenu.Separator className={styles.separator} />
          <DropdownMenu.CheckboxItem
            checked={dotsEnabled}
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
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export function Header({ compact }: { compact: boolean }) {
  const { screen, navigate } = useNavigation();
  const main = SCREEN_ORDER.filter((id) => SCREENS[id].group === 'main');
  const menuScreens = SCREEN_ORDER.filter((id) => SCREENS[id].group !== 'mock');

  return (
    <header className={cx(styles.header, compact && styles.compact)}>
      <button
        type="button"
        className={styles.brand}
        onClick={() => navigate('landing')}
        aria-label="Медиамонитор — на главную"
      >
        <Logo size={compact ? 24 : 28} />
        <span className={styles.brandName}>Медиамонитор</span>
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
        <DemoBadge short={compact} />
        <ScreensMenu
          screens={menuScreens}
          current={screen}
          onSelect={(id) => navigate(id)}
          size={compact ? 'sm' : 'md'}
        />
        <ViewMenu size={compact ? 'sm' : 'md'} />
        {/* Выйти из предпросмотра панели — переключатель в панели «Демо-сценарий». */}
      </div>
    </header>
  );
}
