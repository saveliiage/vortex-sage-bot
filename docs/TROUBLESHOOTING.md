# Решение проблем

> Если бот не работает — начни отсюда. Каждая проблема описана: как выглядит, причина, что делать.

## 1. «Telegram token invalid» (неверный токен)

**Как выглядит:** в логах ошибка `Unauthorized` или `invalid token`, бот не запускается.

**Причина:** токен в `.env` неправильный или просрочен.

**Что делать:**

1. Проверь что в `.env` поле `BOT_TOKEN` заполнено:
   ```bash
   grep BOT_TOKEN .env
   ```
   Должен быть длинный набор цифр и букв, например `1234567890:ABCdefGH...`

2. Если токен выглядит правильно, возможно он был отозван. Получи новый:
   - Открой [@BotFather](https://t.me/BotFather)
   - `/mybots` → выбери бота → `API Token` → `Revoke current token`
   - Скопируй новый токен

3. Обнови `.env`:
   ```bash
   nano .env
   # Замени старый токен на новый
   ```

4. Перезапусти бота:
   ```bash
   sudo docker compose up -d --build
   ```

## 2. «Postgres not healthy» (база данных не поднимается)

**Как выглядит:** бот ждёт и не запускается, в логах `waiting for postgres`, `connection refused`, или PostgreSQL постоянно перезапускается.

**Причина:** контейнер PostgreSQL не может запуститься.

**Что делать:**

1. Посмотри логи PostgreSQL:
   ```bash
   sudo docker compose logs postgres
   ```

2. Частая причина — повреждённый том данных. Сбрось том:

   ⚠️ **Это удалит ВСЕ данные в базе!** Если есть бэкап — сначала восстановишь из него после сброса.

   ```bash
   # Останови всё
   sudo docker compose down

   # Удали том с данными
   sudo docker volume rm vortex-pgdata

   # Запусти заново — PostgreSQL создаст чистую базу
   sudo docker compose up -d
   sudo docker compose run --rm bot ./scripts/migrate.sh

   # Если был бэкап — восстанови
   sudo docker compose run --rm bot ./scripts/restore-db.sh backups/<файл>.dump
   ```

3. Другая причина — занят порт 5432. Проверь:
   ```bash
   sudo lsof -i :5432
   ```
   Если показывает процесс — кто-то занял порт. Останови этот процесс или измени порт в `docker-compose.yml`.

4. После исправления проверь что база жива:
   ```bash
   sudo docker compose ps postgres
   ```
   Колонка `STATUS` должна показывать `Up (healthy)`.

## 3. «Migrations failed» (миграции не проходят)

**Как выглядит:** при запуске бота или ручном `migrate.sh` — ошибка SQL или `alembic` error.

**Причина:** структура базы не совпадает с ожидаемой.

**Что делать:**

1. Посмотри точную ошибку:
   ```bash
   sudo docker compose run --rm bot ./scripts/migrate.sh
   ```

2. Если ошибка про «уже существует» (таблица, колонка уже есть):
   - Это обычно не страшно. Попробуй вручную проставить текущую версию миграции:
   ```bash
   # Посмотри последнюю миграцию
   ls migrations/versions/
   # Найди файл с самым новым ID (например ab12cd34ef56_*.py)
   # Проставь её как текущую:
   sudo docker compose run --rm bot alembic stamp ab12cd34ef56
   ```

3. Если миграция необратима (нельзя откатить) и база сломана:
   - Восстанови базу из бэкапа:
   ```bash
   sudo docker compose run --rm bot ./scripts/restore-db.sh backups/<файл>.dump
   ```
   - Затем попробуй миграции снова

4. Если ничего не помогает — сообщи Саве или разработчику с текстом ошибки.

## 4. «YouTube cookies missing/stale» (cookies отсутствуют или устарели)

**Как выглядит:** YouTube-ссылки не скачиваются, ошибка `Sign in to confirm you're not a bot`, `HTTP Error 403`, или `unable to extract video data`.

**Причина:** YouTube требует cookies для скачивания, а текущий файл cookies устарел или отсутствует.

**Что делать:**

1. Проверь есть ли файл cookies:
   ```bash
   sudo docker compose exec bot ls -la /app/cookies/youtube.txt
   ```
   Если файла нет — смотри шаг 2.

2. Получи свежие cookies. Для этого нужен компьютер с Chrome:

   **Способ А: автоматический (если есть доступ к коду)**
   ```bash
   # Запусти Chrome с удалённой отладкой
   # Затем обнови cookies
   python refresh_cookies.py
   ```

   **Способ Б: вручную через расширение**
   1. Установи расширение Chrome: «Get cookies.txt LOCALLY»
   2. Открой YouTube, войди в аккаунт
   3. Нажми на иконку расширения → «Export»
   4. Сохрани файл как `cookies/youtube.txt` в папке проекта

3. После получения файла — обнови том cookies:
   ```bash
   # Скопируй файл в том Docker
   sudo docker compose cp cookies/youtube.txt bot:/app/cookies/youtube.txt
   sudo docker compose restart bot
   ```

   Или пересоздай том:
   ```bash
   # Загрузи cookies в том (работает только когда контейнер запущен)
   docker cp cookies/youtube.txt vortex-bot:/app/cookies/youtube.txt
   ```

4. Проверь — отправь боту любую YouTube-ссылку.

## 5. «No space left on device» (закончилось место на диске)

**Как выглядит:** бот перестаёт скачивать, в логах `No space left on device`, `disk full`.

**Причина:** диск забит — файлами бота или другими процессами.

**Что делать:**

1. Проверь свободное место на диске:
   ```bash
   df -h /
   ```
   Если Use% близок к 100% — диск полный.

2. Узнай что занимает место:
   ```bash
   sudo du -sh /opt/vortex/downloads 2>/dev/null
   sudo du -sh /opt/vortex/cache 2>/dev/null
   sudo docker system df
   sudo du -sh /var/lib/docker
   ```

3. Очисти загрузки и кэш бота:
   ```bash
   sudo docker compose exec bot rm -rf /app/downloads/*
   sudo docker compose exec bot rm -rf /app/cache/*
   ```

4. Очисти Docker-мусор:
   ```bash
   # Неиспользуемые образы, контейнеры, тома
   sudo docker system prune -a
   # На запрос подтверждения нажми y и Enter
   ```

5. Если место всё ещё кончается — ищи что ещё занимает диск:
   ```bash
   sudo du -sh /* 2>/dev/null | sort -hr | head -10
   ```

## 6. «Bot container restarts in loop» (бот бесконечно перезапускается)

**Как выглядит:** `docker compose ps` показывает бот в статусе `Restarting`, в логах циклично повторяются одни и те же ошибки.

**Причина:** бот падает при запуске, а Docker пытается его перезапустить.

**Что делать:**

1. Посмотри логи — в них будет конкретная ошибка:
   ```bash
   sudo docker compose logs --tail=50 bot
   ```

2. Частые причины:
   - Не заполнен `.env`: проверь `BOT_TOKEN`, `GOOGLE_AI_API_KEY`
   - База не поднялась: смотри проблему 2 выше
   - Ошибка импорта в коде: смотри на первую ошибку в логах (обычно `ImportError` или `ModuleNotFoundError`)

3. Останови бесконечный цикл чтобы спокойно починить:
   ```bash
   sudo docker compose stop bot
   # Почини проблему (см. лог выше)
   # Затем запусти снова:
   sudo docker compose up -d bot
   ```

4. После исправления убедись что бот стартует без ошибок:
   ```bash
   sudo docker compose logs -f bot
   # Подожди 10 секунд — если новых ошибок нет, всё ок. Ctrl+C для выхода
   ```

## 7. «API key missing/rate-limited» (проблемы с API-ключами)

**Как выглядит:** саммарайз не работает, ошибка `API key not valid`, `quota exceeded`, или `429 Too Many Requests`.

**Причина:** проблема с ключом `GOOGLE_AI_API_KEY`.

**Что делать:**

### Если ключ неверный или отсутствует

1. Проверь заполнен ли ключ:
   ```bash
   grep GOOGLE_AI_API_KEY .env
   ```
   Должно быть: `GOOGLE_AI_API_KEY=AIzaSyD...` (не пусто)

2. Получи новый ключ:
   - [Google AI Studio](https://aistudio.google.com/apikey)
   - «Get API Key» → «Create API Key»
   - Скопируй ключ

3. Обнови `.env` и перезапусти:
   ```bash
   nano .env
   sudo docker compose up -d --build
   ```

### Если превышен лимит (quota exceeded)

У бесплатного Gemini есть дневной лимит запросов. Если бот пишет `quota exceeded` или `429`:

- Подожди до следующего дня — лимит сбросится автоматически
- Или создай новый API-ключ на другом Google-аккаунте

## 8. Бот не отвечает в Telegram

**Как выглядит:** отправляешь ссылку боту — тишина, нет ответа.

**Что делать:**

1. Убедись что бот запущен:
   ```bash
   sudo docker compose ps bot
   ```
   STATUS должен быть `Up`.

2. Проверь что контейнер видит интернет:
   ```bash
   sudo docker compose exec bot curl -s -o /dev/null -w "%{http_code}" https://api.telegram.org
   ```
   Должен вернуть `200` или любой не-пустой код. Если ошибка соединения — проблема с интернетом на сервере.

3. Проверь логи на наличие ошибок:
   ```bash
   sudo docker compose logs --tail=20 bot
   ```

4. Отправь `/start` боту. Если бот отвечает на `/start` но не на ссылки — возможно это специфичная проблема с платформой (YouTube, TikTok и т.д.). Смотри проблему 4 (YouTube) или проверь `APIFY_TOKEN` для TikTok/Instagram.

## 9. Проблемы с TikTok / Instagram

**Как выглядит:** TikTok или Instagram ссылки не скачиваются.

**Причина:** скорее всего проблема с `APIFY_TOKEN`.

**Что делать:**

1. Проверь заполнен ли `APIFY_TOKEN`:
   ```bash
   grep APIFY_TOKEN .env
   ```

2. Если пусто — получи токен:
   - [Apify Console](https://console.apify.com/) → Settings → Integrations
   - Скопируй API token

3. Если токен есть но не работает — возможно закончился лимит на Apify. Проверь в консоли Apify остаток.

## Если ничего не помогло

1. Сделай бэкап БД (проблема решаема — данные сохранятся):
   ```bash
   ./scripts/backup-db.sh
   ```

2. Сохрани логи:
   ```bash
   sudo docker compose logs bot > /tmp/vortex_crash.log 2>&1
   sudo docker compose logs postgres >> /tmp/vortex_crash.log 2>&1
   ```

3. Отправь файл `/tmp/vortex_crash.log` Саве или разработчику с описанием «что делал → что пошло не так».

4. Не пытайся чинить код сам, если не понимаешь что делаешь — лучше спросить.
