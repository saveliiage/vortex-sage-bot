# Переменные окружения (Environment Variables)

> Все переменные окружения Vortex. Что обязательно, что опционально, где взять.

## Как это работает

Бот читает настройки из файла `.env`. Файл создаётся один раз при деплое:

```bash
cp .env.example .env   # копируем шаблон
nano .env               # редактируем
```

**Никогда не коммить `.env` в Git!** Он в `.gitignore`, так что Git его проигнорирует автоматически.

Каждая переменная выглядит так:
```
ИМЯ_ПЕРЕМЕННОЙ=значение
```

Без кавычек, без пробелов вокруг `=`. Если значение содержит пробелы — заверни в кавычки:
```
MY_VAR="значение с пробелами"
```

## Обязательные переменные

Без них бот не запустится.

### `BOT_TOKEN`

Токен Telegram-бота.

Где взять:
1. Открой Telegram, напиши [@BotFather](https://t.me/BotFather)
2. Команда `/newbot`
3. Придумай имя бота (например: `Vortex Media`)
4. Придумай username (например: `vortex_media_bot`)
5. BotFather пришлёт токен — длинная строка из цифр, букв и двоеточий

```
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
```

### `OWNER_TELEGRAM_IDS`

Telegram ID владельца (или нескольких через запятую). Владелец обходит любые квоты.

Где взять:
1. Открой Telegram, напиши [@userinfobot](https://t.me/userinfobot)
2. Нажми `/start`
3. Бот скажет твой ID — число

```
OWNER_TELEGRAM_IDS=123456789
```

Если владельцев несколько:
```
OWNER_TELEGRAM_IDS=123456789,987654321
```

### `GOOGLE_AI_API_KEY`

API-ключ для Google Gemini (саммарайз видео).

Где взять:
1. Открой [Google AI Studio](https://aistudio.google.com/apikey)
2. Нажми «Get API Key» → «Create API Key»
3. Скопируй ключ

```
GOOGLE_AI_API_KEY=AIzaSyD-abcdefghijklmnopqrstuvwxyz12345
```

### `POSTGRES_PASSWORD`

Пароль для базы данных PostgreSQL.

Придумай сам. Требования:
- минимум 8 символов
- не используй `change-me` (это шаблонное значение)
- можно буквы, цифры, спецсимволы

```
POSTGRES_PASSWORD=мой_надёжный_пароль_2025
```

## Переменные с дефолтными значениями

Можно не менять — значения по умолчанию уже рабочие.

### `POSTGRES_DB`

Имя базы данных. По умолчанию: `vortex`

```
POSTGRES_DB=vortex
```

### `POSTGRES_USER`

Пользователь базы данных. По умолчанию: `vortex`

```
POSTGRES_USER=vortex
```

### `VORTEX_DATABASE_URL`

Полный URL подключения к базе данных.

По умолчанию формируется автоматически в `docker-compose.yml`:
```
VORTEX_DATABASE_URL=postgresql+psycopg://vortex:change-me@postgres:5432/vortex
```

⚠️ Если меняешь `POSTGRES_USER`, `POSTGRES_PASSWORD` или `POSTGRES_DB` — обнови эту строку соответствующим образом.

Если используешь внешнюю базу (не контейнер postgres в Compose), замени `postgres:5432` на реальный адрес и порт:
```
VORTEX_DATABASE_URL=postgresql+psycopg://vortex:пароль@моя-база.хостинг.com:5432/vortex
```

## Опциональные переменные

Без них бот запустится, но некоторые функции не будут работать.

### `SUMMARY_MODEL`

Модель Gemini для саммарайза. По умолчанию: `gemini-2.0-flash`

```
SUMMARY_MODEL=gemini-2.0-flash
```

### `SUMMARY_MAX_TOKENS`

Максимальная длина саммарайза в токенах. По умолчанию: `2000`

```
SUMMARY_MAX_TOKENS=2000
```

### `OPENROUTER_API_KEY`

API-ключ [OpenRouter](https://openrouter.ai/keys) — для будущих расширений. Сейчас не используется, можно оставить пустым.

```
OPENROUTER_API_KEY=
```

### `APIFY_TOKEN`

Токен [Apify](https://console.apify.com/) — для скачивания с TikTok и как fallback для Instagram. Без него эти платформы могут не работать.

Где взять:
1. Зарегистрируйся на [Apify](https://console.apify.com/)
2. Settings → Integrations → скопируй API token

```
APIFY_TOKEN=apify_api_abc123...
```

### `DOWNLOAD_DIR`

Папка для временных загрузок внутри контейнера. По умолчанию: `/app/downloads`

```
DOWNLOAD_DIR=/app/downloads
```

### `YT_COOKIES_FILE`

Путь к файлу cookies YouTube внутри контейнера. По умолчанию: `/app/cookies/youtube.txt`

```
YT_COOKIES_FILE=/app/cookies/youtube.txt
```

Cookies нужны для скачивания с YouTube. Как обновить — смотри [TROUBLESHOOTING.md](TROUBLESHOOTING.md), секция «YouTube cookies missing/stale».

## Deprecated (устаревшие)

Эти переменные пока читаются кодом для обратной совместимости, но в новом коде не должны использоваться.

### `ALLOWED_USER_ID`

Устаревший способ указать владельца бота. Заменён на `OWNER_TELEGRAM_IDS`.

### `VORTEX_DB_PATH`

Устаревший путь к SQLite-файлу. Заменён на PostgreSQL через `VORTEX_DATABASE_URL`.

Можешь не заполнять эти переменные — бот будет работать без них.

## Пример заполненного .env

Ниже пример для локального запуска. На реальном сервере — значения будут другие.

```env
# Telegram
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
OWNER_TELEGRAM_IDS=123456789

# База данных
POSTGRES_DB=vortex
POSTGRES_USER=vortex
POSTGRES_PASSWORD=мой_надёжный_пароль_2025
VORTEX_DATABASE_URL=postgresql+psycopg://vortex:мой_надёжный_пароль_2025@postgres:5432/vortex

# AI / провайдеры
GOOGLE_AI_API_KEY=AIzaSyD-abcdefghijklmnopqrstuvwxyz12345
SUMMARY_MODEL=gemini-2.0-flash
SUMMARY_MAX_TOKENS=2000
OPENROUTER_API_KEY=
APIFY_TOKEN=apify_api_abc123...

# Пути внутри контейнера
DOWNLOAD_DIR=/app/downloads
YT_COOKIES_FILE=/app/cookies/youtube.txt
```
