# Zapolnyator – Telegram Gateway

Это первый микросервис системы автоматического заполнения отчёта ДКП. Он принимает от пользователя два файла (Excel-шаблон и MXL-выгрузку из 1С), сохраняет их на сервер и передаёт управление **Orchestrator** (в разработке).

---

## Архитектура системы (общая)

- **Telegram Gateway** – текущий сервис.
- **Orchestrator** – управляет бизнес-процессом, вызывает DeepSeek, координирует Worker.
- **Worker Engine** – выполняет тяжёлые вычисления (парсинг MXL, обработка Excel, расчёт метрик).

Взаимодействие через REST API и Redis.

---

## Технологии

- Python 3.11
- aiogram 3.x
- Docker / Docker Compose
- Redis (для состояний и очередей)
- GitHub Actions (автоматический деплой на VPS)

---

## Текущий функционал (Telegram Gateway)

- Принимает команды `/start`, `/help`, `/reset`.
- Принимает Excel-файлы (.xlsx, .xls) и MXL-файлы (.mxl) в любом порядке, в том числе в одном сообщении.
- Сохраняет файлы в папку `temp` на сервере.
- Подтверждает загрузку и сообщает пути к файлам.
- (Пока не вызывает Orchestrator, только заглушка).

---

## Установка и развёртывание

### Локальная разработка

1. Клонируйте репозиторий:
   ```bash
   git clone git@github.com:greenscale93/Zapolnyator.git
   cd Zapolnyator

2. Создайте файл .env с токеном бота:

text
TELEGRAM_BOT_TOKEN=ваш_токен
TEMP_DIR=./temp

3. Запустите:

bash
docker compose up -d --build
Автоматический деплой на VPS
Настроен GitHub Actions. При пуше в ветку main происходит:

Клонирование репозитория на VPS (через SSH-ключ).

Обновление кода (git fetch && git reset --hard origin/main).

Пересборка и перезапуск контейнеров.

Для этого в GitHub Secrets должны быть заданы:

VPS_HOST

VPS_USER

VPS_SSH_KEY (приватный ключ для входа на VPS)

TELEGRAM_BOT_TOKEN

Структура проекта
text
Zapolnyator/
├── .github/workflows/deploy.yml   # CI/CD
├── docker-compose.yml
├── telegram-gateway/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/
│       ├── main.py                # точка входа
│       ├── handlers.py            # логика обработки сообщений
│       ├── client.py              # клиент к Orchestrator (заглушка)
│       └── models.py              # (пока пустой)
├── temp/                          # временные файлы (создаётся автоматически)
└── README.md
Планы развития (ближайшие)
Реализовать Orchestrator – FastAPI-сервис с интеграцией DeepSeek, управление сессиями, памятью SQLite, вызов Worker.

Реализовать Worker – парсинг MXL, бизнес-логика, заполнение Excel, расчёт метрик.

Связать все сервисы через REST API и Redis.

Добавить очистку временных файлов после обработки.

Обеспечить логирование с correlation_id для трассировки задач.

Как дорабатывать через ИИ
При обращении к ИИ (например, ChatGPT) указывайте:

Что уже сделано (ссылайтесь на этот README).

Какую новую функциональность нужно добавить.

Ожидаемый результат и требования из ТЗ.

Контакты
Разработчик: [Ваше имя или ник]
Проект: https://github.com/greenscale93/Zapolnyator