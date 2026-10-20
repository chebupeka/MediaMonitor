/**
 * TODO(Э-Расширение): демо-страница «новость на сайте СМИ» и узкая раскладка.
 * - Выделенный текст → всплывающая кнопка «Найти, где это опубликовано» →
 *   боковая панель с результатом (setLayout('panel') + navigate('spread', { text })).
 * - `HostPage` — страница, которую оболочка показывает слева от боковой панели
 *   в режиме предпросмотра «Боковая панель». Экспорт обязателен.
 * - Узкая раскладка остальных экранов — через контейнерные запросы
 *   `@container screen (max-width: 560px)`, см. web/README.md.
 *
 * Ниже — временная заготовка. Замените её целиком.
 */
import { Search } from 'lucide-react';
import { demoQueries } from '@/api';
import { ScreenStub } from '@/app/ScreenStub';
import { useNavigation, type ScreenProps } from '@/app/navigation';
import { useShell } from '@/app/shell-state';
import { Button, Screen } from '@/components';
import styles from './demo-page.module.css';

const RELEASE = demoQueries.find((q) => q.id === 'release')?.text ?? '';

/** Страница сайта СМИ (вымышленного) со статьёй — «хозяин» для боковой панели. */
export function HostPage() {
  const { setLayout } = useShell();
  const { navigate } = useNavigation();
  const paragraphs = RELEASE.split('\n\n');
  return (
    <div className={styles.host}>
      <div className={styles.chrome} aria-hidden="true">
        <span className={styles.dots}>
          <i />
          <i />
          <i />
        </span>
        <span className={styles.address}>
          novosti-kraya.demo / образование / новая-школа-в-норильске
        </span>
      </div>
      <article className={styles.article} aria-label="Демо-страница сайта СМИ">
        <p className={styles.site}>Новости края · демо-сайт СМИ</p>
        <h2 className={styles.headline}>В Норильске открылась новая школа на 1 100 мест</h2>
        <p className={styles.date}>14 октября 2026, 11:30</p>
        {paragraphs.map((p) => (
          <p key={p.slice(0, 24)} className={styles.paragraph}>
            {p}
          </p>
        ))}
        <Button
          size="sm"
          variant="primary"
          iconStart={<Search />}
          onClick={() => {
            setLayout('panel');
            navigate('spread', { text: RELEASE });
          }}
        >
          Найти, где это опубликовано (временно — вместо выделения)
        </Button>
      </article>
    </div>
  );
}

export default function DemoPageScreen(_props: ScreenProps<'demo-page'>) {
  return (
    <Screen
      title="Демо-страница *СМИ*"
      lead="Так расширение работает на сайте СМИ: выделите текст новости и найдите, где ещё она вышла."
      eyebrow="Только в мокапе"
    >
      <ScreenStub
        owner="Э-Расширение"
        folder="src/screens/demo-page"
        refs="Р1; SC-21; НТ-27; бриф, раздел «Р. Расширение»"
        items={[
          'Выделение текста → всплывающая кнопка «Найти, где это опубликовано»',
          'Боковая панель 360–400 px с результатом — тот же интерфейс, что и на сайте',
          'Сообщение «нет связи с сервером» в панели; минимальная длина выделения',
        ]}
      />
      <HostPage />
    </Screen>
  );
}
