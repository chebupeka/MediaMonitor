import type { QueryKind, ResultGroup, SelectionNotice, TopicUnderstanding } from '../../types';
import type { DemoItem } from '../build';

export interface ReleaseMeta {
  title: string;
  text: string;
  fragments: { id: string; index: number; text: string }[];
}

/** Демо-набор: всё, что имитация знает о результатах одного вида запроса. */
export interface Dataset {
  id: 'bdd' | 'release' | 'event' | 'large' | 'empty';
  kind: QueryKind;
  /** Короткая подпись запроса для строки состояния */
  label: string;
  items: DemoItem[];
  /** Записи, которые попадают в подборку, только если грань перенесли в «входит» */
  optional: { facetId: string; items: DemoItem[] }[];
  /** Записи вне подборки, которые можно добавить по ссылке (П8) */
  spare: DemoItem[];
  /** Группы (состав заполняется при поиске) */
  groups: ResultGroup[];
  topic: TopicUnderstanding | null;
  /** Для поиска по тексту новости — релиз и его фрагменты */
  release: ReleaseMeta | null;
  notices?: SelectionNotice[];
}
