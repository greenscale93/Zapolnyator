---
description: "Use when deploying to VPS, checking deployment status, diagnosing container issues, or testing the Zapolnyator bot after deploy. Covers git push, GitHub Actions tracking, VPS container checks, log analysis, and end-to-end Telegram testing."
applyTo: ["**/DEPLOYMENT.md", ".github/workflows/deploy.yml"]
---

# Инструкция по деплою и тестированию Zapolnyator

## Деплой — строго 4 шага

Никаких лишних действий. Только эти шаги, строго по порядку:

### Шаг 1. `git push origin main`
```bash
git add -A
git commit -m "<описание изменений>"
git push origin main
```

### Шаг 2. Отследить GitHub Actions
Проверить **минимальным запросом** — только статус последнего workflow run:
- Запросить `https://api.github.com/repos/greenscale93/Zapolnyator/actions/runs?event=push&per_page=1`
- Проверить 2 поля: `status=completed` и `conclusion=success`
- Не читать логи, не скачивать файлы, не делать повторных запросов в цикле
- Если `conclusion=failure` — сообщить пользователю и остановиться

### Шаг 3. Проверить контейнеры на VPS
```bash
ssh root@31.130.131.233 "cd /home/root/Zapolnyator && docker compose ps"
```
Проверить что все 4 контейнера в статусе `Up`:
- `zapolnyator-orchestrator-1`
- `zapolnyator-worker-1`
- `zapolnyator-telegram-gateway-1`
- `zapolnyator-redis-1`

### Шаг 4. Если контейнер не поднялся
```bash
docker logs zapolnyator-<service>-1 --tail=80
```
Искать `Traceback` в логах. Исправить → commit → push → повторная проверка.
