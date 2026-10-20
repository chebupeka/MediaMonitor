import { useEffect, useState } from 'react';
import { api } from '@/api';
import type { PlatformId, PlatformInfo } from '@/api/types';
import { PLATFORM_ORDER } from '@/lib/labels';

/** Один запрос на всё приложение: список площадок меняется только с перезапуском сервера. */
let loading: Promise<PlatformInfo[]> | null = null;

function load(): Promise<PlatformInfo[]> {
  loading ??= api
    .getStartState()
    .then((s) => s.platforms.filter((p) => p.enabled))
    .catch(() => {
      loading = null;
      return [];
    });
  return loading;
}

export interface ServerPlatforms {
  /** Площадки, по которым ищет сервер, в порядке `PLATFORM_ORDER`. */
  ids: PlatformId[];
  /** Их описание от сервера: откуда данные и оговорки (`note`). Пусто, пока не пришло. */
  info: PlatformInfo[];
}

/**
 * Площадки этого сервера (`StartState.platforms`, только включённые) — для текстов «где ищем».
 * Пока ответа нет (или он не пришёл), считаем, что работают все площадки `PLATFORM_ORDER`.
 */
export function useServerPlatforms(): ServerPlatforms {
  const [info, setInfo] = useState<PlatformInfo[]>([]);
  useEffect(() => {
    let alive = true;
    void load().then((list) => {
      if (alive) setInfo(list);
    });
    return () => {
      alive = false;
    };
  }, []);
  const ids =
    info.length > 0
      ? PLATFORM_ORDER.filter((id) => info.some((p) => p.id === id))
      : [...PLATFORM_ORDER];
  return { ids, info };
}
