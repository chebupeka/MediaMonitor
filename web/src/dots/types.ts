/**
 * Интерфейс слота «Точки» (08-visual-concept.md). Экраны используют только
 * `<DotsScene … />` с этими props. Исполнитель «Точки» заменяет реализацию
 * (Three.js, лениво, с запасной 2D-версией), не меняя интерфейс.
 */
import type { PlatformId } from '@/api/types';

/** Во что собираются точки — словарь форм по моментам продукта. */
export type DotsForm =
  | 'krai' // лендинг, покой: силуэт края, Енисей
  | 'listening' // ввод запроса: облако оживает
  | 'searching' // идёт поиск: три облака VK / OK / MAX, точки текут на карту
  | 'found' // найдено: загораются города с публикациями
  | 'spread' // распространение: вспышка из источника и волны
  | 'empty' // пусто: точки рассеиваются и гаснут
  | 'failure' // сбой площадки: облако площадки серое и мерцает
  | 'export'; // выгрузка: точки складываются в сетку таблицы

/** Публикации в городе: точек-данных ровно столько, сколько публикаций (правило честности 1). */
export interface DotsCityCount {
  /** Название города в именительном падеже — как в `RegionReason.places` */
  city: string;
  count: number;
  platform?: PlatformId;
}

export type DotsPlatformState = 'idle' | 'active' | 'done' | 'failed';

export interface DotsSceneProps {
  form: DotsForm;
  /** `full` — лендинг; `calm` — рабочая панель: спокойно, не мешает читать */
  intensity?: 'full' | 'calm';
  /** Для `found` и `spread`: города с публикациями. Без региона — не на карте (правило 2). */
  cities?: readonly DotsCityCount[];
  /** Для `searching` и `failure`: состояние облака каждой площадки */
  platforms?: Partial<Record<PlatformId, DotsPlatformState>>;
  /** Для `spread`: город первоисточника */
  sourceCity?: string;
  /** Высота области; ширина — по контейнеру */
  height?: number | string;
  className?: string;
}
