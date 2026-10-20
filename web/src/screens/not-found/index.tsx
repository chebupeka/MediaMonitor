/**
 * Неизвестный адрес веб-версии (`/app/что-то`): вместо молча открытого «Поиска» — честное
 * «такого раздела нет» и переходы в разделы (аудит веб-версии, Ж10).
 */
import { Search } from 'lucide-react';
import { useNavigation, type ScreenProps } from '@/app/navigation';
import { Button, EmptyState, Screen } from '@/components';

const SECTIONS = [
  ['sources', 'Источники'],
  ['recent', 'Недавние поиски'],
  ['how', 'Как это работает'],
] as const;

export default function NotFoundScreen(_props: ScreenProps<'not-found'>) {
  const { navigate } = useNavigation();
  return (
    <Screen
      eyebrow="Адрес не найден"
      title="Такого *раздела нет*"
      lead="Возможно, в адресе опечатка или ссылку скопировали не целиком. Ваши поиски и источники на месте."
      width="narrow"
    >
      <EmptyState
        title="Откройте нужный раздел"
        actions={
          <>
            <Button variant="primary" iconStart={<Search />} onClick={() => navigate('search')}>
              К поиску
            </Button>
            {SECTIONS.map(([id, label]) => (
              <Button key={id} variant="secondary" onClick={() => navigate(id)}>
                {label}
              </Button>
            ))}
          </>
        }
      />
    </Screen>
  );
}
