/**
 * Реестр экранов. Оболочка показывает экран по его id. Экран живёт в своей папке
 * src/screens/<имя>/index.tsx и экспортирует компонент по умолчанию.
 * Новый экран добавляет только «Основа» или лид.
 */
import type { ComponentType } from 'react';
import DemoPageScreen, { HostPage } from '@/screens/demo-page';
import HowScreen from '@/screens/how';
import LandingScreen from '@/screens/landing';
import RecentScreen from '@/screens/recent';
import SearchScreen from '@/screens/search';
import SourcesScreen from '@/screens/sources';
import SpreadScreen from '@/screens/spread';
import StatusScreen from '@/screens/status';
import GalleryScreen from './Gallery';
import type { ScreenId, ScreenProps } from './navigation';

export interface ScreenMeta {
  id: ScreenId;
  /** Заголовок окна браузера и объявление для скринридера */
  title: string;
  /** Подпись в навигации */
  navLabel: string;
  /** `main` — верхняя навигация, `secondary` — подвал, `mock` — только в мокапе */
  group: 'home' | 'main' | 'secondary' | 'mock';
  /** Кто делает экран (бриф, «Как делим работу») */
  owner: string;
}

export const SCREENS: Record<ScreenId, ScreenMeta> = {
  landing: {
    id: 'landing',
    title: 'Медиамонитор',
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
  'sources',
  'recent',
  'how',
  'status',
  'demo-page',
  'gallery',
];

export const SCREEN_COMPONENTS: { [K in ScreenId]: ComponentType<ScreenProps<K>> } = {
  landing: LandingScreen,
  search: SearchScreen,
  spread: SpreadScreen,
  sources: SourcesScreen,
  recent: RecentScreen,
  how: HowScreen,
  status: StatusScreen,
  'demo-page': DemoPageScreen,
  gallery: GalleryScreen,
};

/** Страница-«хозяин» слева от боковой панели в режиме предпросмотра расширения. */
export { HostPage };
