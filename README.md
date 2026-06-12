# 🌀 Vortex — Telegram Media Bot

Telegram-бот для скачивания, анализа и конвертации медиа. Отправь ссылку — получи видео, аудио, саммарайз или кружочек.

## Функции

- 📎 **Скачивание видео** — YouTube, Twitter/X, Vimeo и любые сайты, которые поддерживает yt-dlp
- 🎵 **Скачивание аудио** — извлечение MP3 из любого видео
- 📝 **Саммарайз YouTube** — скачивает авто-субтитры → Gemini делает саммарайз с разделами и таймкодами
- 🎵 **Поиск музыки** — `/music <запрос>` — поиск через YouTube Music
- 🔵 **Кружочки** — конвертация любого видео в Telegram video note (640x640)
- 🎙️ **Голосовые** — конвертация любого аудиофайла в Telegram voice note (OGG/Opus)
- 🖼 **Превью** — скачивание обложки видео
- ℹ️ **Инфо о видео** — метаданные: длительность, размер, платформа
- 💾 **Сохранение в Obsidian** — транскрипты с саммарайзом в vault

## Поддерживаемые платформы

| Платформа | Видео | Аудио | Метод |
|-----------|-------|-------|-------|
| YouTube | ✅ | ✅ | yt-dlp + cookies |
| Instagram | ✅ | ✅ | Embed API → Apify fallback |
| TikTok | ✅ | ✅ | Apify (VPS IP blocked) |
| Twitter/X | ✅ | ✅ | yt-dlp |
| Vimeo, Dailymotion, др. | ✅ | ✅ | yt-dlp |

## Production deployment architecture

Новый production-контракт: **локально проверяем на ноутбуке → архитектура сразу VPS-ready → на VPS деплоим только когда Сава явно скажет**. Целевой стек: PostgreSQL + Docker Compose + VPS runbook. SQLite-код в `core/access.py` считается поведенческим прототипом и будет заменён на Postgres/migrations перед production-деплоем.

Документы:

- [`docs/DEPLOYMENT_ARCHITECTURE.md`](docs/DEPLOYMENT_ARCHITECTURE.md) — целевая архитектура деплоя, БД, env, rollback и CI.
- [`docs/AGENT_TASKS_DB_AND_DEPLOY.md`](docs/AGENT_TASKS_DB_AND_DEPLOY.md) — подробные брифы для DB/DevOps/Docs/CI агентов.

Runbook для оператора (Дед/не-разработчик):

- [`docs/DEPLOY.md`](docs/DEPLOY.md) — пошаговая инструкция деплоя (локально + VPS).
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — ежедневные операции: обновление, бэкап, логи, откат.
- [`docs/ENV.md`](docs/ENV.md) — все переменные окружения, что обязательно, где взять.
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — решение частых проблем.

## Быстрый старт

### Docker Compose (рекомендуется)

```bash
# 1. Клонируй
git clone https://github.com/saveliiage/vortex-sage-bot.git
cd vortex-sage-bot

# 2. Настрой .env
cp .env.example .env
nano .env
# Заполни BOT_TOKEN, OWNER_TELEGRAM_IDS, GOOGLE_AI_API_KEY
# Поменяй POSTGRES_PASSWORD

# 3. Запусти (бот + PostgreSQL)
docker compose up -d --build

# 4. Проверь логи
docker compose logs -f bot
```

Полезные команды:
```bash
docker compose logs -f bot           # логи
docker compose restart bot           # перезапуск бота
docker compose down                  # остановить всё
docker compose run --rm bot ./scripts/smoke-check.sh   # дымовой тест
docker compose run --rm bot ./scripts/migrate.sh       # миграции БД
./scripts/backup-db.sh                                  # бэкап БД
./scripts/restore-db.sh backups/<file>.dump             # восстановить БД
```

### Локально (venv, для разработки)

```bash
# 1. Клонируй
git clone https://github.com/saveliiage/vortex-sage-bot.git
cd vortex-sage-bot

# 2. Виртуальное окружение
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Настрой .env
cp .env.example .env
# Заполни BOT_TOKEN, OWNER_TELEGRAM_IDS, GOOGLE_AI_API_KEY

# 4. Запусти
python bot.py
```

## YouTube cookies

Для скачивания с YouTube бот использует `--cookies-from-browser chromium` — читает cookies напрямую из профиля запущенного Chromium. Никаких файлов cookies.txt, никакого `refresh_cookies.py`. Пока Chromium жив и залогинен в YouTube — работает бессрочно.

Требование: `vortex-chromium.service` должен быть запущен и залогинен в YouTube (один раз через noVNC при старте).

## Структура проекта

```
├── bot.py              # Точка входа
├── config.py           # Конфигурация из .env
├── refresh_cookies.py  # Извлечение cookies из Chromium
├── core/
│   ├── downloader.py   # Роутинг по платформам
│   ├── progress.py     # Async прогресс-бары для yt-dlp / ffmpeg
│   ├── summarizer.py   # LiteLLM → Gemini — саммарайз субтитров
│   ├── music.py        # Поиск и скачивание музыки
│   ├── circle.py       # Конвертация в video note (кружок)
│   ├── voice.py        # Конвертация аудио в voice note (голосовое)
│   ├── instagram.py    # Instagram: embed + Apify fallback
│   ├── apify_tiktok.py # TikTok через Apify
│   ├── transcriber.py  # faster-whisper (локальный STT)
│   └── vault.py        # Сохранение транскриптов в Obsidian
└── handlers/
    ├── download.py     # Обработчики скачивания с прогрессом
    ├── menu.py         # Inline-меню и callback routing
    ├── music.py        # Обработчик /music
    └── voice.py        # Обработчик аудио → голосовое
```

## Systemd сервис

```ini
[Unit]
Description=Vortex — Telegram Media Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vortex
ExecStart=/opt/vortex/venv/bin/python /opt/vortex/bot.py
Restart=always
RestartSec=5
EnvironmentFile=/opt/vortex/.env

[Install]
WantedBy=multi-user.target
```

## Стек

- **python-telegram-bot** 21.10 — async Telegram bot framework
- **yt-dlp** — загрузка видео (700+ сайтов)
- **faster-whisper** — локальный speech-to-text
- **httpx** — HTTP-клиент для Gemini API
- **ffmpeg** — конвертация в кружочки и MP3
- **Google Gemini** — анализ и саммарайз видео
