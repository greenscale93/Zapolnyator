# Деплой и диагностика

## Как происходит деплой

1. Вы делаете `git push` в ветку `main`
2. GitHub Actions (`.github/workflows/deploy.yml`) автоматически деплоит на VPS
3. Docker Compose перезапускает сервисы с обновлёнными образами

## Типичные ошибки после деплоя

### 🔴 ImportError — конфликт module.py и module/ пакета
**Симптом**: контейнер `zapolnyator-orchestrator-1` перезапускается (Restarting).
**Логи**: `ImportError: cannot import name 'X' from 'src.Y'`
**Причина**: если есть и `module.py`, и `module/` (пакет), Python загружает пакет, игнорируя файл.
**Решение**: перенести код в `module/core.py`, в `__init__.py` добавить `from .core import ClassName`, удалить `module.py`.

### 🔴 ValueError — неразрывные пробелы в данных
**Симптом**: ошибка `could not convert string to float: '138\xa0000'`
**Причина**: данные из 1С содержат `\xa0` (неразрывный пробел).
**Решение**: использовать `_clean_numeric()` — удаляет `\xa0`, пробелы, меняет запятые на точки.

### 🔴 Пропадают формулы в Excel
**Симптом**: после обработки в шаблоне исчезают формулы, остаются только значения.
**Причина**: `openpyxl.load_workbook(..., data_only=True)` читает кешированные значения, а не формулы.
**Решение**: при записи в файл открывать БЕЗ `data_only=True`.

## Проверка деплоя

После каждого пуша агент:
1. **Опрашивает GitHub Actions API** — ждёт `status=completed` и `conclusion=success`
2. **SSH на VPS** → `docker compose ps` — все контейнеры должны быть `Up`
3. Если какой-то `Restarting` → `docker logs zapolnyator-<service>-1 --tail=80` → ищет `Traceback`
4. Исправляет → commit → push → повторная проверка
5. Если всё `Up` — уведомляет об успехе

### Если нужно вручную

```bash
ssh root@31.130.131.233
cd /home/root/Zapolnyator
docker compose ps
docker logs zapolnyator-orchestrator-1 --tail=50
```

Возможные имена контейнеров:
- `zapolnyator-orchestrator-1`
- `zapolnyator-worker-1`
- `zapolnyator-telegram-gateway-1`
- `zapolnyator-redis-1`
