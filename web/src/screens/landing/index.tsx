/**
 * Лендинг (Л). Заготовка «Основы»: фраза ценности, «Начать поиск»,
 * «Установить расширение» (окно с тремя шагами), «Как это работает», честные рамки.
 * Карта края — через слот <DotsScene form="krai" />; 3D-версию делает «Э-Точки».
 */
import { ArrowRight, Download, Puzzle, Search } from 'lucide-react';
import { useState } from 'react';
import { useNavigation, type ScreenProps } from '@/app/navigation';
import { useShell } from '@/app/shell-state';
import { Button, DemoBadge, Dialog, DialogClose } from '@/components';
import { DotsScene } from '@/dots';
import { extraCoverage, platformsNames, platformsWhere } from '@/lib/labels';
import { useServerPlatforms } from '@/app/platforms';
import styles from './landing.module.css';

/** Место в тексте, куда подставляется список площадок сервера */
const PLATFORMS_MARK = '{площадки}';

const STEPS = [
  {
    title: 'Опишите тему или вставьте новость',
    text: 'Одно поле на всё: тема своими словами, событие, человек или текст релиза. Период — готовыми кнопками или в календаре.',
  },
  {
    title: 'Система ищет в соцсетях и СМИ края',
    // Начало — площадки от сервера, подставляются при показе (PLATFORMS_MARK)
    text: `${PLATFORMS_MARK}. В подборку попадают только публикации о Красноярском крае — и у каждой видно, почему.`,
  },
  {
    title: 'Проверьте и выгрузите',
    text: 'У каждой публикации прямая ссылка и выдержка из оригинала. Лишнее исключите, остальное скачайте в XLSX.',
  },
];

const FRAMES = [
  PLATFORMS_MARK,
  'Только Красноярский край',
  'Только публичные посты',
  'Текст на картинках не анализируется',
];

const INSTALL_STEPS = [
  {
    title: 'Скачайте архив и распакуйте его',
    text: 'В любую папку на компьютере, например в «Документы». Прав администратора не нужно.',
  },
  {
    title: 'Включите режим разработчика',
    text: 'Откройте страницу расширений: в Яндекс Браузере — browser://extensions, в Chrome — chrome://extensions. Включите переключатель «Режим разработчика».',
  },
  {
    title: 'Загрузите распакованное расширение',
    text: 'Нажмите «Загрузить распакованное» и выберите папку из первого шага. Значок Медиарадара появится на панели браузера.',
  },
];

export default function LandingScreen(_props: ScreenProps<'landing'>) {
  const { navigate } = useNavigation();
  // Где ищем — от сервера (StartState.platforms), с честной оговоркой о покрытии
  const { ids, info } = useServerPlatforms();
  const names = platformsNames(ids);
  const withPlatforms = (text: string) => text.replace(PLATFORMS_MARK, names);
  const coverage = extraCoverage(info);
  const { setLayout } = useShell();
  const [installOpen, setInstallOpen] = useState(false);

  return (
    <div className={styles.landing}>
      <section className={styles.hero} data-scope="dark" aria-labelledby="landing-title">
        <div className={styles.heroInner}>
          <div className={styles.heroText}>
            <div className={styles.kicker}>
              <span>Медиарадар · Красноярский край</span>
              <DemoBadge />
            </div>
            <h1 id="landing-title" className={styles.value}>
              Найдём, где в соцсетях и СМИ края написали о вашей теме или новости
            </h1>
            <p className={styles.sub}>
              Публикации {platformsWhere(ids)} — с прямой ссылкой на каждый пост, выдержкой из
              оригинала и выгрузкой в Excel.
            </p>
            <div className={styles.ctas}>
              <Button
                variant="primary"
                size="lg"
                iconStart={<Search />}
                onClick={() => navigate('search')}
              >
                Начать поиск
              </Button>
              <Button
                variant="secondary"
                size="lg"
                iconStart={<Puzzle />}
                onClick={() => setInstallOpen(true)}
              >
                Установить расширение
              </Button>
            </div>
            <ul className={styles.frames} aria-label="Рамки поиска">
              {FRAMES.map((f) => (
                <li key={f}>{withPlatforms(f)}</li>
              ))}
            </ul>
            {/* Площадок больше обязательных — и честно, с каким покрытием (note сервера) */}
            {coverage && (
              <p className={styles.coverage}>
                Начали с обязательных соцсетей и подключаем площадки дальше. Сейчас — {coverage}.
              </p>
            )}
          </div>
          <div className={styles.heroMap}>
            <DotsScene form="krai" intensity="full" />
            <p className={styles.mapCaption}>Красноярский край — от Саян до Таймыра</p>
          </div>
        </div>
      </section>

      <section className={styles.how} aria-labelledby="how-title">
        <div className={styles.howHead}>
          <h2 id="how-title" className={styles.howTitle}>
            Как это работает
          </h2>
          <Button variant="link" iconEnd={<ArrowRight />} onClick={() => navigate('how')}>
            Подробнее: откуда данные и как идёт отбор
          </Button>
        </div>
        <ol className={styles.steps}>
          {STEPS.map((step, i) => (
            <li key={step.title} className={styles.step}>
              <span className={styles.stepNumber} aria-hidden="true">
                {i + 1}
              </span>
              <h3 className={styles.stepTitle}>{step.title}</h3>
              <p className={styles.stepText}>{withPlatforms(step.text)}</p>
            </li>
          ))}
        </ol>
        <p className={styles.note}>
          Проверить поиск можно прямо на сайте, без установки. Расширение — та же панель сбоку от
          любой страницы, плюс поиск по выделенному тексту.
        </p>
      </section>

      <Dialog
        open={installOpen}
        onOpenChange={setInstallOpen}
        title="Установить расширение"
        description="Та же панель Медиарадара — сбоку от любой страницы. Установка занимает 2–3 минуты."
        size="md"
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => {
                setInstallOpen(false);
                setLayout('panel');
              }}
            >
              Посмотреть, как выглядит панель
            </Button>
            <DialogClose>
              <Button variant="primary">Понятно</Button>
            </DialogClose>
          </>
        }
      >
        <ol className={styles.install}>
          {INSTALL_STEPS.map((step, i) => (
            <li key={step.title} className={styles.installStep}>
              <span className={styles.installNumber} aria-hidden="true">
                {i + 1}
              </span>
              <div>
                <h3 className={styles.installTitle}>{step.title}</h3>
                <p className={styles.installText}>{step.text}</p>
                {i === 0 && (
                  <div className={styles.installAction}>
                    <Button size="sm" iconStart={<Download />} disabled aria-describedby="zip-note">
                      Скачать архив .zip
                    </Button>
                    <span id="zip-note" className={styles.mockNote}>
                      В мокапе файл не скачивается
                    </span>
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>
        <p className={styles.installFoot}>
          Если на рабочем компьютере режим разработчика запрещён, пользуйтесь сайтом: он умеет всё
          то же, кроме поиска по выделенному тексту.
        </p>
      </Dialog>
    </div>
  );
}
