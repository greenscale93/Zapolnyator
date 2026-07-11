# Деплой и диагностика

## Как происходит деплой

1. Вы делаете `git push` в ветку `main`
2. GitHub Actions (`.github/workflows/deploy.yml`) автоматически деплоит на VPS
3. Docker Compose перезапускает сервисы с обновлёнными образами

## Если сервис упал после деплоя

ИИ-агент **не может** самостоятельно подключаться по SSH — у него нет SSH-клиента.
Поэтому схема работы такая:

### 1. Вы подключаетесь по SSH

```bash
ssh root@8567269-pm074185
cd /home/root/Zapolnyator
```

### 2. Проверяете состояние контейнеров

```bash
docker compose ps
```

Находите, какой контейнер не в статусе `Up`.

### 3. Смотрите логи упавшего контейнера

```bash
docker logs zapolnyator-orchestrator-1 --tail=50
```

Возможные имена контейнеров:
- `zapolnyator-orchestrator-1`
- `zapolnyator-worker-1`
- `zapolnyator-telegram-gateway-1`
- `zapolnyator-redis-1`

### 4. Копируете сюда логи

Агент проанализирует ошибку и предложит/внесёт исправления.

### 5. После исправления

```text
(агент делает commit → push → GitHub Actions передеплоит автоматически)
```
