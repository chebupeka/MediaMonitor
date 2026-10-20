/**
 * Слот «Точки» — папка исполнителя «Э-Точки». Экраны импортируют отсюда только
 * `DotsScene` и типы; всё остальное в папке — внутреннее дело исполнителя.
 */
export { DotsScene } from './DotsScene';
export { DotsStage, type DotsStageProps } from './DotsStage';
export { KRAI_CITIES } from './krai-geo';
export type { DotsCityCount, DotsForm, DotsPlatformState, DotsSceneProps } from './types';
