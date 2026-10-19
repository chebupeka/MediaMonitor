/** Правка источника: название, тип, город или район (П13, SC-10). Ссылку не меняем. */
import { useState } from 'react';
import { api, errorMessage } from '@/api';
import type { Source, SourceType } from '@/api/types';
import { Button, Dialog, DialogClose, PlatformDot, StatusBadge, TextField } from '@/components';
import { formatDateTime } from '@/lib/format';
import { PLATFORMS } from '@/lib/labels';
import { checkView, ORIGIN_LABEL, shortUrl, subscribersText } from './model';
import { DistrictField, OutLink, TypeField } from './fields';
import styles from './sources.module.css';

export interface EditSourceDialogProps {
  source: Source;
  districts: readonly string[];
  onOpenChange: (open: boolean) => void;
  onSaved: (source: Source) => void;
}

export function EditSourceDialog({
  source,
  districts,
  onOpenChange,
  onSaved,
}: EditSourceDialogProps) {
  const [name, setName] = useState(source.name);
  const [type, setType] = useState<SourceType>(source.type);
  const [district, setDistrict] = useState(source.district ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const view = checkView(source.check);
  const nameError = name.trim() ? undefined : 'Название не может быть пустым';
  const changed =
    name.trim() !== source.name ||
    type !== source.type ||
    (district.trim() || null) !== source.district;

  const save = async (): Promise<void> => {
    if (nameError || !changed) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateSource(source.id, {
        name: name.trim(),
        type,
        district: district.trim() || null,
      });
      onSaved(updated);
      onOpenChange(false);
    } catch (e) {
      setError(errorMessage(e));
      setSaving(false);
    }
  };

  return (
    <Dialog
      open
      onOpenChange={onOpenChange}
      size="md"
      title="Изменить источник"
      description="Название, тип и район видны в списке, в карточках подборки и в выгрузке."
      footer={
        <>
          <DialogClose>
            <Button>Отмена</Button>
          </DialogClose>
          <Button
            variant="primary"
            disabled={!changed || Boolean(nameError)}
            loading={saving}
            onClick={() => void save()}
          >
            Сохранить
          </Button>
        </>
      }
    >
      <form
        className={styles.dialogStack}
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className={styles.verdict}>
          <p className={styles.previewName}>
            <PlatformDot platform={source.platform} />
            <span>
              {source.name}
              <span className={styles.sourcePlatform}> · {PLATFORMS[source.platform].name}</span>
            </span>
          </p>
          <p className={styles.previewFacts}>
            {subscribersText(source.subscribers)} · {ORIGIN_LABEL[source.origin]}{' '}
            {formatDateTime(source.addedAt)}
          </p>
          <OutLink href={source.url}>{shortUrl(source.url)}</OutLink>
          <p>
            <StatusBadge tone={view.tone} icon={view.icon} size="sm">
              {view.text}
            </StatusBadge>
          </p>
        </div>
        <TextField
          label="Название"
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={nameError}
        />
        <TypeField value={type} onChange={setType} />
        <DistrictField
          id={`edit-${source.id}`}
          value={district}
          onChange={setDistrict}
          districts={districts}
        />
        <p className={styles.muted}>
          Ссылку изменить нельзя: если группа переехала, удалите её и добавьте новую ссылку.
        </p>
        {error && (
          <p className={styles.errorText} role="alert">
            {error}
          </p>
        )}
      </form>
    </Dialog>
  );
}
