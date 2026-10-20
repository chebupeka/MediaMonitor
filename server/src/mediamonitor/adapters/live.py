"""Настоящие адаптеры обязательных площадок — каждый в своём файле.

- VK — `adapters/vk_live.py`: VK API с сервисным ключом (`wall.get` сообществ, кэш в базе);
- OK — `adapters/ok_live.py`: публичные страницы групп ok.ru без входа;
- MAX — `adapters/max_live.py`: сторонний индекс MaxStat + проверка ссылок на max.ru.

Заготовки с TODO, что лежали здесь, заменены настоящими адаптерами; модуль оставлен для
прежних импортов. Общее правило для всех трёх (§7.1): поиск или список даёт кандидатов,
каждая ссылка перед показом проверяется живым запросом (`fetch_post`), ключи — только из
переменных окружения на сервере (НТ-15). Сбор — только с сервера, без логинов
пользователей (Р2).
"""

from __future__ import annotations

from mediamonitor.adapters.max_live import MaxAdapter
from mediamonitor.adapters.ok_live import OkAdapter
from mediamonitor.adapters.vk_live import VkAdapter

__all__ = ["MaxAdapter", "OkAdapter", "VkAdapter"]
