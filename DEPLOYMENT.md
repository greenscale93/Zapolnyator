# Деплой и диагностика

## Как происходит деплой

1. Вы делаете `git push` в ветку `main`
2. GitHub Actions (`.github/workflows/deploy.yml`) автоматически деплоит на VPS
3. Docker Compose перезапускает сервисы с обновлёнными образами

## Автоматическая проверка после деплоя

ИИ-агент может **самостоятельно** отследить деплой и проверить сервисы.

После каждого пуша агент:
1. **Опрашивает GitHub Actions API** (каждые 10 сек), пока workflow не завершится
2. **Проверяет conclusion** — если не `success`, сообщает об ошибке
3. **SSH на VPS** и выполняет `docker compose ps`
4. Если все контейнеры `Up` — уведомляет об успехе
5. Если какой-то упал — смотрит логи и исправляет ошибку

Это работает быстрее и точнее, чем ожидание фиксированного таймаута.

### Если автоматическая проверка не сработала

Можно выполнить вручную:

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
