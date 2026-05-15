# Деплой Vortex

> **Текущий режим: локальная проверка на ноутбуке.**
> На VPS деплоим только когда Сава явно скажет: «деплой на VPS».
> Архитектура сразу VPS-готовая, но сейчас работаем локально.

## Что тебе понадобится

- Ubuntu-сервер (20.04 или новее) с доступом по SSH
- Доступ к sudo
- Docker Engine + Docker Compose v2
- Git

## Шаг 1: Установка Docker на VPS

Если Docker ещё не установлен — выполни эти команды по очереди:

```bash
# Обнови пакеты
sudo apt update && sudo apt upgrade -y

# Установи зависимости
sudo apt install -y ca-certificates curl

# Добавь Docker-репозиторий
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Установи Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Проверь установку
sudo docker --version
sudo docker compose version
```

Ожидаемый результат: обе команды показывают версию без ошибок.

## Шаг 2: Первый деплой (локально или на VPS)

Эти команды выполняются из домашней директории (`cd ~`). Если на сервере уже есть старая папка `/opt/vortex` — скрипт сам её переименует, ничего не удалит.

```bash
# Перейди в /opt
cd /opt

# Если уже есть старая папка vortex — отодвинь её
if [ -d vortex ]; then sudo mv vortex vortex_old_$(date +%Y%m%d_%H%M%S); fi

# Клонируй свежий репозиторий
sudo git clone https://github.com/saveliiage/vortex-sage-bot.git vortex
cd vortex

# Скопируй шаблон .env
sudo cp .env.example .env
```

Теперь нужно заполнить `.env` файл:
```bash
sudo nano .env
```

Что заполнить (подробнее — в [ENV.md](ENV.md)):
- `BOT_TOKEN` — токен бота. Как получить: напиши [@BotFather](https://t.me/BotFather) в Telegram → `/newbot` → следуй инструкциям
- `OWNER_TELEGRAM_IDS` — твой Telegram ID (узнай через [@userinfobot](https://t.me/userinfobot))
- `GOOGLE_AI_API_KEY` — ключ из [Google AI Studio](https://aistudio.google.com/apikey)
- `POSTGRES_PASSWORD` — придумай надёжный пароль для базы

Сохрани: `Ctrl+O` → Enter → `Ctrl+X`.

Запусти бота:

```bash
# Сборка и запуск
sudo docker compose up -d --build

# Смотри логи — если нет ошибок, бот жив
sudo docker compose logs -f bot
```

Для выхода из логов нажми `Ctrl+C`. Бот продолжит работать в фоне.

## Шаг 3: Проверь, что бот работает

```bash
# Дымовой тест — проверяет что контейнер живой и код запускается
sudo docker compose run --rm bot ./scripts/smoke-check.sh
```

Ожидаемый результат: `SMOKE_OK — all checks passed.`

Теперь открой Telegram и отправь боту любую YouTube-ссылку. Бот должен ответить меню с выбором действия (скачать видео, аудио, саммарайз и т.д.).

## Локальная разработка (ноутбук, не VPS)

Для проверки кода на ноутбуке используй те же команды, но без `sudo` (если Docker настроен без sudo) и без клонирования в `/opt`:

```bash
# Ты уже в папке проекта (например ~/projects/vortex)
cp .env.example .env
nano .env

# Сборка и запуск локально
docker compose up -d --build
docker compose logs -f bot
```

## Важно

- ⚠️ **Не коммить `.env` файл** — он в `.gitignore`, Git его проигнорирует
- ⚠️ **Пароль от БД** (`POSTGRES_PASSWORD`) хранится только в `.env` на сервере. Если потеряешь — придётся сбрасывать
- ⚠️ **На VPS деплоим только когда Сава скажет.** Сейчас все проверки — на ноутбуке
- Docker Compose поднимает два контейнера: `vortex-bot` (сам бот) и `vortex-postgres` (база данных)
