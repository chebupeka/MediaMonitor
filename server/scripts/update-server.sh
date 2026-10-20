#!/usr/bin/env bash
# Обновить стенд на сервере команды до последней версии ветки и перезапустить:
#
#   ssh team-27@109.196.167.227 /opt/mediamonitor/app/server/scripts/update-server.sh
#
# Берёт ветку BRANCH (по умолчанию integration/full) только перемоткой вперёд, пересобирает
# образ без модели на CPU (compose.server.yaml), применяет миграции, ждёт /health.
# Данные базы (том pgdata) и настройки (server/.env) не трогает.
set -euo pipefail

main() {
  cd "$(dirname "$(readlink -f "$0")")/.."
  local branch="${BRANCH:-integration/full}"
  git fetch --quiet origin "$branch"
  git merge --ff-only --quiet "origin/$branch"
  echo "Версия: $(git log -1 --format='%h %s')"
  docker compose -f compose.yaml -f compose.server.yaml up -d --build --remove-orphans
  for _ in $(seq 1 60); do
    if curl -fsS -m 3 http://127.0.0.1:8000/health; then
      echo
      docker image prune -f >/dev/null
      return 0
    fi
    sleep 2
  done
  echo "API не ответил за 2 минуты: docker compose logs api" >&2
  return 1
}

main "$@"
