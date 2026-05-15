# 🌀 Vortex — Telegram Media Bot

Telegram-бот для скачивания, анализа и конвертации медиа. Отправь ссылку — получи видео, аудио, саммарайз или кружочек.

## Функции

- 📎 **Скачивание видео** — YouTube, Twitter/X, Vimeo и любые сайты, которые поддерживает yt-dlp
- 🎵 **Скачивание аудио** — извлечение MP3 из любого видео
- 📝 **Саммарайз YouTube** — скачивает авто-субтитры → Gemini делает саммарайз с разделами и таймкодами
- 🎵 **Поиск музыки** — `/music <запрос>` — поиск через YouTube Music
- 🔵 **Кружочки** — конвертация любого видео в Telegram video note (640x640)
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

Документы для следующего этапа:

- [`docs/DEPLOYMENT_ARCHITECTURE.md`](docs/DEPLOYMENT_ARCHITECTURE.md) — целевая архитектура деплоя, БД, env, rollback и CI.
- [`docs/AGENT_TASKS_DB_AND_DEPLOY.md`](docs/AGENT_TASKS_DB_AND_DEPLOY.md) — подробные брифы для DB/DevOps/Docs/CI агентов.

## Быстрый старт

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
# Заполни BOT_TOKEN, ALLOWED_USER_ID, GOOGLE_AI_API_KEY

# 4. Запусти
python bot.py
```

## YouTube cookies

Для скачивания с YouTube нужны свежие cookies. Бот ожидает Netscape-файл по пути `cookies/youtube.txt`.

Для обновления cookies используется `refresh_cookies.py` — извлекает cookies из Chromium через Chrome DevTools Protocol (требует запущенный Chrome с `--remote-debugging-port=9222`).

## Структура проекта

```
├── bot.py              # Точка входа
├── config.py           # Конфигурация из .env
├── refresh_cookies.py  # Извлечение cookies из Chromium
├── core/
│   ├── downloader.py   # Роутинг по платформам
│   ├── progress.py     # Async прогресс-бары для yt-dlp / ffmpeg
│   ├── summarizer.py   # Gemini API — саммарайз субтитров
│   ├── music.py        # Поиск и скачивание музыки
│   ├── circle.py       # Конвертация в video note
│   ├── instagram.py    # Instagram: embed + Apify fallback
│   ├── apify_tiktok.py # TikTok через Apify
│   ├── transcriber.py  # faster-whisper (локальный STT)
│   └── vault.py        # Сохранение транскриптов в Obsidian
└── handlers/
    ├── download.py     # Обработчики скачивания с прогрессом
    ├── menu.py         # Inline-меню и callback routing
    └── music.py        # Обработчик /music
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
