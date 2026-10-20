/**
 * Сцена точек во весь отведённый блок — как формы на сайте «Медиарадар»: крупно, главный
 * визуальный акцент экрана. Высоту задаёт родитель (`Screen` со сценой, окно «Файл готов»).
 * Подпись — те же факты текстом для всех, кто не смотрит на картинку (тихо, внизу сцены,
 * как подпись к карте на сайте).
 */
import type { ReactNode } from 'react';
import { DotsScene } from './DotsScene';
import type { DotsSceneProps } from './types';
import styles from './DotsStage.module.css';

export interface DotsStageProps extends Omit<DotsSceneProps, 'height'> {
  /** Подпись: что показывают точки — текстом */
  caption?: ReactNode;
  /** Подпись меняется по ходу поиска — объявлять скринридеру */
  live?: boolean;
  /** Где подпись: внизу справа (как на сайте) или по центру */
  captionAlign?: 'end' | 'center';
}

export function DotsStage({
  caption,
  live = false,
  captionAlign = 'end',
  className,
  ...scene
}: DotsStageProps) {
  return (
    <figure className={[styles.stage, className].filter(Boolean).join(' ')}>
      <div className={styles.canvas}>
        <DotsScene {...scene} height="100%" />
      </div>
      {caption && (
        <figcaption
          className={captionAlign === 'center' ? styles.captionCenter : styles.caption}
          {...(live ? { role: 'status' } : {})}
        >
          {caption}
        </figcaption>
      )}
    </figure>
  );
}
