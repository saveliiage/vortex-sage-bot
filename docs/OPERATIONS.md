# Операции с Vortex

> **Текущий режим: локальная проверка на ноутбуке.**
> На VPS — только когда Сава скажет «деплой».

Все команды ниже выполняются из папки проекта (обычно `/opt/vortex` на VPS, или `~/projects/vortex` локально). На VPS команды через `sudo`, локально — зависит от настройки Docker.

## Обычное обновление (новый код из GitHub)

```bash
cd /opt/vortex
git pull --ff-only origin main
sudo docker compose up -d --build
sudo docker compose logs -f bot
```

- `git pull --ff-only` — безопасное обновление, не затрёт локальные изменения
- `up -d --build` — пересобирает контейнер если изменился Dockerfile и перезапускает
- `logs -f` — смотри логи, убедись что нет ошибок

Если `git pull` ругается «локальные изменения», значит кто-то менял файлы руками на сервере. Напиши Саве или разработчику, сам не разбирайся.

## Перезапуск бота

```bash
sudo docker compose restart bot
```

Бот перезапустится за 2-3 секунды. База данных не перезапускается.

## Остановить всё

```bash
sudo docker compose down
```

Останавливает и бота и базу. Данные в базе и на томах сохраняются.

## Запустить после остановки

```bash
sudo docker compose up -d
```

Без `--build` — использует уже собранный образ. Если обновлял код, всегда делай `up -d --build`.

## Посмотреть логи

```bash
# Логи бота (последние 100 строк)
sudo docker compose logs --tail=100 bot

# Логи в реальном времени (Ctrl+C чтобы выйти)
sudo docker compose logs -f bot

# Логи базы данных
sudo docker compose logs --tail=50 postgres
```

## Проверить состояние контейнеров

```bash
sudo docker compose ps
```

Показывает список контейнеров. Колонка `STATUS` должна показывать `Up` и время работы. Если `Restarting` или `Exited` — что-то не так (смотри [TROUBLESHOOTING.md](TROUBLESHOOTING.md)).

## Бэкап базы данных

```bash
# Создать бэкап
./scripts/backup-db.sh
```

Бэкап сохраняется в папку `backups/` с именем `vortex_20240515_143000.dump` (цифры = дата и время).

Если скрипт говорит «не в Docker», запускай внутри контейнера:

```bash
sudo docker compose run --rm bot ./scripts/backup-db.sh
```

Делай бэкап перед каждым обновлением! Это займёт 5 секунд и спасёт данные.

## Восстановление базы из бэкапа

```bash
# Посмотри список бэкапов
ls -lh backups/

# Восстанови нужный (осторожно — перезапишет текущую базу!)
sudo docker compose run --rm bot ./scripts/restore-db.sh backups/vortex_20240515_143000.dump
```

Скрипт спросит подтверждение — набери `yes` и Enter.

После восстановления обязательно запусти миграции:
```bash
sudo docker compose run --rm bot ./scripts/migrate.sh
```

## Миграции базы (обновление структуры БД)

```bash
sudo docker compose run --rm bot ./scripts/migrate.sh
```

Обычно миграции запускаются автоматически при старте бота. Но вручную — для проверки или после восстановления бэкапа.

## Откат кода (rollback)

Если после обновления что-то сломалось:

```bash
cd /opt/vortex

# Посмотри историю коммитов (последние 10)
git log --oneline -10

# Откатись на стабильный коммит (замени HASH на нужный)
git reset --hard abc1234

# Пересобери и запусти
sudo docker compose up -d --build
sudo docker compose logs -f bot
```

Если откат кода не помог — возможно миграция БД необратимая. Тогда:
1. Восстанови базу из бэкапа (команда выше)
2. Потом откати код

## Очистка загрузок и кэша

Иногда папка загрузок разрастается:

```bash
# Посмотри сколько места занимают загрузки
sudo docker compose exec bot du -sh /app/downloads
sudo docker compose exec bot du -sh /app/cache

# Очисти загрузки старше 7 дней
sudo docker compose exec bot find /app/downloads -mtime +7 -delete

# Или очисти всё
sudo docker compose exec bot rm -rf /app/downloads/*
sudo docker compose exec bot rm -rf /app/cache/*
```

## Проверка текущего git-коммита

```bash
cd /opt/vortex
git log --oneline -1
```

Показывает последний коммит — полезно когда нужно понять «а какая версия сейчас на сервере?»

## Проверка свободного места

```bash
# На диске
df -h /

# Использование Docker
sudo docker system df
```

Если `docker system df` показывает много гигабайт в `Build Cache`:
```bash
sudo docker builder prune -a
```

## Дымовой тест (smoke check)

Быстрая проверка что контейнер жив и код работает:

```bash
sudo docker compose run --rm bot ./scripts/smoke-check.sh
```

Ожидаемый результат: `SMOKE_OK — all checks passed.`

## Вход в контейнер (для отладки)

```bash
sudo docker compose exec bot bash
```

Ты внутри контейнера. Для выхода набери `exit`.

## Сводка команд

| Действие | Команда |
|----------|---------|
| Обновить | `git pull --ff-only && docker compose up -d --build` |
| Перезапустить | `docker compose restart bot` |
| Остановить | `docker compose down` |
| Запустить | `docker compose up -d` |
| Логи | `docker compose logs -f bot` |
| Статус | `docker compose ps` |
| Бэкап БД | `./scripts/backup-db.sh` |
| Восстановить БД | `./scripts/restore-db.sh backups/<файл>` |
| Миграции | `docker compose run --rm bot ./scripts/migrate.sh` |
| Smoke-check | `docker compose run --rm bot ./scripts/smoke-check.sh` |
