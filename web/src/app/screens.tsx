/**
 * Реестр экранов. Оболочка показывает экран по его id. Экран живёт в своей папке
 * src/screens/<имя>/index.tsx и экспортирует компонент по умолчанию.
 * Новый экран добавляет только «Основа» или лид.
 */
import type { ComponentType } from 'react';
import AiCheckScreen from '@/screens/ai-check';
import HowScreen from '@/screens/how';
import NotFoundScreen from '@/screens/not-found';
import RecentScreen from '@/screens/recent';
import SearchScreen from '@/screens/search';
import SourcesScreen from '@/screens/sources';
import SpreadScreen from '@/screens/spread';
import StatusScreen from '@/screens/status';
// Экраны мокапа; в веб-версии их подменяют заглушки (src/app/mock-only.web.tsx)
import { DemoPageScreen, GalleryScreen, HostPage, LandingScreen } from '@/app/mock-only';
import type { ScreenId, ScreenProps } from './navigation';

export interface ScreenMeta {
  id: ScreenId;
  /** Заголовок окна браузера и объявление для скринридера */
  title: string;
  /** Подпись в навигации */
  navLabel: string;
  /**
   * `main` — верхняя навигация, `secondary` — подвал, `mock` — только в мокапе,
   * `hidden` — ни в одном меню (служебный экран «Такого раздела нет»)
   */
  group: 'home' | 'main' | 'secondary' | 'mock' | 'hidden';
  /** Кто делает экран (бриф, «Как делим работу») */
  owner: string;
}

export const SCREENS: Record<ScreenId, ScreenMeta> = {
  landing: {
    id: 'landing',
    title: 'Медиарадар',
    navLabel: 'Главная',
    group: 'home',
    owner: 'Основа',
  },
  search: { id: 'search', title: 'Поиск', navLabel: 'Поиск', group: 'main', owner: 'Э-Поиск' },
  spread: {
    id: 'spread',
    title: 'Распространение',
    navLabel: 'Распространение',
    group: 'main',
    owner: 'Э-Распространение',
  },
  'ai-check': {
    id: 'ai-check',
    title: 'Проверка на ИИ',
    navLabel: 'Проверка на ИИ',
    group: 'main',
    owner: 'Э-ИИ-интерфейс',
  },
  sources: {
    id: 'sources',
    title: 'Источники',
    navLabel: 'Источники',
    group: 'main',
    owner: 'Э-Источники',
  },
  recent: {
    id: 'recent',
    title: 'Недавние поиски',
    navLabel: 'Недавние',
    group: 'main',
    owner: 'Э-Источники',
  },
  how: {
    id: 'how',
    title: 'Как это работает',
    navLabel: 'Как это работает',
    group: 'main',
    owner: 'Э-Источники',
  },
  status: {
    id: 'status',
    title: 'Состояние стенда',
    navLabel: 'Состояние стенда',
    group: 'secondary',
    owner: 'Э-Источники',
  },
  'not-found': {
    id: 'not-found',
    title: 'Раздел не найден',
    navLabel: 'Раздел не найден',
    group: 'hidden',
    owner: 'Основа',
  },
  'demo-page': {
    id: 'demo-page',
    title: 'Демо-страница СМИ',
    navLabel: 'Демо-страница СМИ',
    group: 'mock',
    owner: 'Э-Расширение',
  },
  gallery: {
    id: 'gallery',
    title: 'Базовые компоненты',
    navLabel: 'Базовые компоненты',
    group: 'mock',
    owner: 'Основа',
  },
};

export const SCREEN_ORDER: readonly ScreenId[] = [
  'landing',
  'search',
  'spread',
  'ai-check',
  'sources',
  'recent',
  'how',
  'status',
  'not-found',
  'demo-page',
  'gallery',
];

export const SCREEN_COMPONENTS: { [K in ScreenId]: ComponentType<ScreenProps<K>> } = {
  landing: LandingScreen,
  search: SearchScreen,
  spread: SpreadScreen,
  'ai-check': AiCheckScreen,
  sources: SourcesScreen,
  recent: RecentScreen,
  how: HowScreen,
  status: StatusScreen,
  'not-found': NotFoundScreen,
  'demo-page': DemoPageScreen,
  gallery: GalleryScreen,
};

/** Страница-«хозяин» слева от боковой панели в режиме предпросмотра расширения. */
export { HostPage };
