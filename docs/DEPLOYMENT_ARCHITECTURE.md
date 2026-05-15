# Vortex Deployment Architecture

> Status: Phase 0 contract freeze. This document is the source of truth for the next implementation tasks. Agents must follow it unless Sava/Mikee explicitly changes the contract.

## Goal

Make `vortex-sage-bot` a self-contained deployable project while keeping the current work local-first:

- development and validation happen on Sava's laptop first;
- do **not** deploy to or test on the VPS until Sava explicitly asks;
- architecture must stay VPS-ready from the start;
- future production target is a VPS;
- deploy/update/rollback must be reproducible when VPS deployment starts;
- a non-coder can hand the repo and this runbook to an operator such as Dedal;
- `main` should be deployable only after local tests/smoke checks pass.

## Non-negotiable decisions

1. **Production DB: PostgreSQL.**
   - SQLite was only a behavior prototype for plans/quotas/admin audit.
   - Do not build new production code on SQLite.
   - Do not use Supabase for this project unless Sava explicitly changes this decision.
2. **Deploy packaging: Docker Compose.**
   - The VPS should not need manual Python venv management for production.
   - Bot + Postgres + volumes must be declared in repository-owned Compose files.
3. **Secrets: `.env` on the VPS, never committed.**
   - Repository contains `.env.example` only.
   - Real tokens/API keys/database passwords stay on the VPS.
4. **Database changes: migrations, not manual SQL.**
   - Use Alembic migrations or an equivalent explicit migration layer.
   - Migrations must run during deploy/startup through a documented command.
5. **Public product must not depend on Sava's Obsidian vault.**
   - Obsidian export is owner-only/personal extension.
   - Public users get Telegram text/file exports, not vault writes.
6. **VPS old installation is parked, not mutated blindly.**
   - First production deploy should move old code aside and clone cleanly.

## Target repository shape

```text
vortex-sage-bot/
├── bot.py
├── config.py
├── core/
│   ├── db.py                  # Postgres engine/session/connection helpers
│   ├── access.py              # plans, quotas, user access service
│   ├── jobs.py                # persistent Telegram jobs/callback refs
│   └── ...
├── handlers/
├── migrations/
│   ├── env.py
│   └── versions/
├── scripts/
│   ├── migrate.sh
│   ├── smoke-check.sh
│   ├── backup-db.sh
│   └── restore-db.sh
├── tests/
├── .github/workflows/ci.yml
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
├── README.md
└── docs/
    ├── DEPLOYMENT_ARCHITECTURE.md
    ├── AGENT_TASKS_DB_AND_DEPLOY.md
    ├── DEPLOY.md
    ├── OPERATIONS.md
    └── ENV.md
```

## Runtime services

### `bot`

Python Telegram bot container.

Requirements:

- starts from repository Dockerfile;
- reads config from environment variables;
- waits for Postgres to be healthy before starting;
- runs migrations before bot process, or exposes a documented `migrate` command;
- has restart policy `unless-stopped`;
- writes only to declared volumes for downloads/cache/cookies, not random host paths.

### `postgres`

PostgreSQL container for staging/small production VPS.

Requirements:

- persistent named volume for data;
- healthcheck via `pg_isready`;
- credentials sourced from `.env`;
- not publicly exposed unless explicitly needed.

Managed Postgres can replace the Compose `postgres` service later by setting `VORTEX_DATABASE_URL` to the managed database URL.

## Environment contract

Required variables:

```env
# Telegram
BOT_TOKEN=
OWNER_TELEGRAM_IDS=

# Database
POSTGRES_DB=vortex
POSTGRES_USER=vortex
POSTGRES_PASSWORD=change-me
VORTEX_DATABASE_URL=postgresql+psycopg://vortex:change-me@postgres:5432/vortex

# AI/providers
GOOGLE_AI_API_KEY=
OPENROUTER_API_KEY=
APIFY_TOKEN=

# Runtime paths inside container
DOWNLOAD_DIR=/app/downloads
COOKIE_FILE=/app/cookies/youtube.txt

# Product/access defaults
DEFAULT_PLAN=free
```

Deprecated for production:

```env
VORTEX_DB_PATH=
ALLOWED_USER_ID=
```

`OWNER_TELEGRAM_IDS` replaces single-user assumptions. It is a comma-separated list, for example:

```env
OWNER_TELEGRAM_IDS=123456789,987654321
```

## Database schema contract

The first production migration should create at least:

- `users`
- `quota_limits`
- `usage_events`
- `usage_counters`
- `jobs`
- `result_refs`
- `admin_audit`

Plans (`owner`, `free`, `pro`, `creator`, `blocked`) are enumerated values — stored in `users.plan` and `quota_limits.plan` columns. There is no separate `plans` lookup table.

Terminology: DB column `cost_class` holds the action name (e.g., `llm_summary`, `media_download`, `apify`). In prose, "action" and "cost_class" refer to the same concept — "action" is the user-facing term, `cost_class` is the DB identifier.

### Users

Tracks Telegram users and current plan.

Minimum columns:

```text
id uuid/bigserial primary key
telegram_id bigint unique not null
username text
first_name text
language_code text
plan text not null default 'free'
plan_expires_at timestamptz null
status text not null default 'active'
created_at timestamptz not null
updated_at timestamptz not null
last_seen_at timestamptz null
```

### Quotas

`quota_limits` defines limits per plan/action/period.

`usage_counters` is the fast transactional counter table. It must support atomic quota checks.

Quota check contract:

1. Begin DB transaction.
2. Ensure user exists/refresh last seen.
3. Owner plan or owner telegram id bypasses quota.
4. Blocked plan rejects immediately.
5. Lock or upsert the current counter row.
6. If `used_count >= limit_count`, reject without incrementing.
7. Otherwise increment and write `usage_events`.
8. Commit.

Concurrency acceptance test:

- plan limit: `llm_summary` daily limit `3`;
- run `100` parallel quota attempts for same user/action/window;
- exactly `3` succeed;
- exactly `97` are rejected.

### Jobs and callbacks

Handlers must stop relying only on `context.user_data` for source URLs/action state.

Target callback pattern:

```text
callback_data = "vx:summary:<job_id>"
callback_data = "vx:dl_video:<job_id>"
callback_data = "vx:dl_audio:<job_id>"
callback_data = "vx:circle:<job_id>"
callback_data = "vx:thumbnail:<job_id>"
callback_data = "vx:info:<job_id>"
```

`jobs` stores the source URL/ref with TTL so callbacks survive bot restarts.

`thumbnail` and `info` callbacks are non-persistent convenience actions — they read from `context.user_data['url']` and do NOT need a row in `jobs`. They use the `vx:` prefix for consistency but their `job_id` is ignored; they are fallback-safe (if `context.user_data` is gone, the menu is re-shown).

## Deploy contract

### First clean VPS deploy

Do not mutate old code in place. Park it:

```bash
sudo mkdir -p /opt
cd /opt
if [ -d vortex ]; then sudo mv vortex vortex_old_$(date +%Y%m%d_%H%M%S); fi
sudo git clone https://github.com/saveliiage/vortex-sage-bot.git vortex
cd vortex
sudo cp .env.example .env
sudo nano .env
sudo docker compose up -d --build
sudo docker compose logs -f bot
```

### Normal update

```bash
cd /opt/vortex
git pull --ff-only origin main
docker compose up -d --build
docker compose logs -f bot
```

### Rollback

```bash
cd /opt/vortex
git log --oneline -10
git reset --hard <known_good_commit>
docker compose up -d --build
docker compose logs -f bot
```

If a DB migration is irreversible, rollback must use database backup restore. Every migration PR must state whether rollback is code-only or requires DB restore.

## Required scripts

### `scripts/migrate.sh`

Runs migrations against `VORTEX_DATABASE_URL`.

Expected use:

```bash
docker compose run --rm bot ./scripts/migrate.sh
```

### `scripts/smoke-check.sh`

Checks the container can import project modules and see required config shape without calling paid APIs.

Expected use:

```bash
docker compose run --rm bot ./scripts/smoke-check.sh
```

### `scripts/backup-db.sh`

Creates a timestamped Postgres dump.

Expected use:

```bash
./scripts/backup-db.sh
```

### `scripts/restore-db.sh`

Restores a selected dump. Must require an explicit file path and print a destructive-action warning.

## CI contract

GitHub Actions must run on every push/PR:

- install Python deps;
- run unit tests;
- run `python -m compileall .`;
- run smoke check;
- run Docker build or `docker compose config` when Docker files exist.

Goal: before VPS `git pull`, GitHub should already show green checks on `main`.

## Security/privacy rules

- Do not commit `.env`, cookies, DB dumps, downloads, transcripts with private user content, or API tokens.
- Hash source URLs for usage/audit when full URL is not required.
- If full URL is needed for a running job, store it in `jobs` with TTL/cleanup.
- Owner-only features must be gated by `OWNER_TELEGRAM_IDS`.
- Public users must not see local/Obsidian paths.

## Acceptance criteria for Phase 0

This contract is complete when:

- this architecture document is committed;
- agent task prompts exist;
- README links to the deployment architecture;
- no production code changes are made in the same commit.
- all reviewer blockers are resolved in the implementation contract: Obsidian `CONTRACT — Phase 0 Postgres Docker implementation.md`.

See also: `docs/AGENT_TASKS_DB_AND_DEPLOY.md` (agent task prompts).
