# Agent Tasks — DB and VPS Deployment

> Use this file when delegating implementation work. Every agent must receive the relevant task text inline, not just a vague pointer to the file.

## Shared project context for all agents

Project: **Vortex — Telegram Media Bot**

Repository:

```text
/home/hermes/projects/vortex
https://github.com/saveliiage/vortex-sage-bot
```

Current important context:

- The bot is developed locally on Sava's laptop through Hermes/Mikee.
- Production will run on a VPS.
- The VPS currently has old code; first deploy should park old code and clone a clean repo.
- Sava is not a programmer. Repo docs and commands must be beginner-proof and handoff-ready for Dedal/operator.
- SQLite access code currently in `core/access.py` is a behavioral prototype, not production architecture.
- Production decision: PostgreSQL + Docker Compose + migrations.
- Do not use Supabase unless Sava explicitly changes this decision.
- Do not make public product behavior depend on Sava's Obsidian vault.

Read before coding:

```text
docs/DEPLOYMENT_ARCHITECTURE.md
README.md
config.py
core/access.py
tests/test_access.py
tests/test_admin.py
handlers/admin.py
```

Common verification commands:

```bash
pytest -q
python -m compileall .
git diff --stat
```

Common report format:

```text
Summary:
- ...

Files changed:
- path: what changed

Commands run:
- command -> result

Risks / follow-ups:
- ...
```

---

## Task A — Backend DB/Postgres Agent

### Goal

Replace the SQLite access prototype with a production PostgreSQL-backed access layer while preserving the current user/plan/quota/admin behavior.

### Owned files/folders

Allowed to modify/create:

```text
core/access.py
core/db.py
core/jobs.py
config.py
requirements.txt
migrations/**
alembic.ini
tests/test_access.py
tests/test_admin.py
tests/test_quota_concurrency.py
tests/test_jobs.py
scripts/migrate.sh
.env.example
```

Do not edit media download/summarizer behavior unless required for imports/tests.

### Required behavior

Preserve or implement:

- owner bypass;
- plans: `owner`, `free`, `pro`, `creator`, `blocked`;
- daily quotas per action;
- blocked plan rejects;
- `/admin_plan` can set plan and optional expiry;
- admin changes write audit records;
- config uses `OWNER_TELEGRAM_IDS` and `VORTEX_DATABASE_URL`;
- no production dependency on `VORTEX_DB_PATH`.

### Database requirements

Use PostgreSQL with explicit migrations.

Preferred stack:

```text
SQLAlchemy 2.x Core or ORM
psycopg[binary]
Alembic
```

If choosing raw `psycopg`, explain why and still provide a migration mechanism.

Minimum tables:

```text
users
plans
quota_limits
usage_events
usage_counters
admin_audit
```

If implementing persistent jobs in the same task, also:

```text
jobs
result_refs
```

### Concurrency quota requirement

Add a test proving quota increments are transactional:

```text
Given daily llm_summary limit = 3
When 100 parallel attempts happen for the same non-owner user
Then exactly 3 succeed and exactly 97 raise QuotaExceeded / are rejected
```

### Implementation steps

1. Inspect current `core/access.py`, `tests/test_access.py`, `handlers/admin.py`, and `config.py`.
2. Add DB dependency packages to `requirements.txt`.
3. Add `core/db.py` for DB URL parsing/session/connection helper.
4. Add migration scaffolding.
5. Create first migration for access tables.
6. Port `AccessStore` behavior to Postgres.
7. Update tests to use a temporary/test Postgres database or a clearly documented test DB URL.
8. Add concurrency test.
9. Update `.env.example`.
10. Run verification commands.

### Verification

Minimum:

```bash
pytest -q
python -m compileall .
```

If Docker files already exist:

```bash
docker compose run --rm bot ./scripts/migrate.sh
docker compose run --rm bot pytest -q
```

### Output report must include

- exact DB stack chosen;
- migration command;
- test DB assumptions;
- whether rollback is code-only or requires DB restore.

---

## Task B — DevOps/Docker/VPS Agent

### Goal

Make the repo deployable on a VPS with Docker Compose.

### Owned files/folders

Allowed to modify/create:

```text
Dockerfile
docker-compose.yml
.dockerignore
.env.example
scripts/migrate.sh
scripts/smoke-check.sh
scripts/backup-db.sh
scripts/restore-db.sh
docs/DEPLOY.md
docs/OPERATIONS.md
docs/ENV.md
README.md
```

Do not change business logic except tiny config/import fixes required for container startup.

### Required Docker behavior

Compose must define:

- `bot` service;
- `postgres` service;
- persistent Postgres volume;
- downloads/cache/cookies volume or bind mount;
- healthcheck for Postgres;
- restart policy for bot;
- env file loading from `.env`.

The bot container must include:

- Python runtime;
- system packages needed by current app, especially `ffmpeg`;
- project dependencies from `requirements.txt`;
- non-paid smoke check path.

### Required commands to support

First deploy:

```bash
git clone https://github.com/saveliiage/vortex-sage-bot.git
cd vortex-sage-bot
cp .env.example .env
nano .env
docker compose up -d --build
docker compose logs -f bot
```

Update:

```bash
cd /opt/vortex
git pull --ff-only origin main
docker compose up -d --build
docker compose logs -f bot
```

Stop:

```bash
docker compose down
```

Restart:

```bash
docker compose restart bot
```

Logs:

```bash
docker compose logs -f bot
```

Backup:

```bash
./scripts/backup-db.sh
```

Restore:

```bash
./scripts/restore-db.sh backups/<file>.dump
```

### Verification

```bash
docker compose config
docker compose build
docker compose run --rm bot ./scripts/smoke-check.sh
```

If DB layer is ready:

```bash
docker compose run --rm bot ./scripts/migrate.sh
```

### Output report must include

- exact commands tested;
- container names/services;
- volumes created;
- any assumptions about VPS OS.

---

## Task C — Docs/Runbook Agent

### Goal

Write beginner-proof deployment and operations docs that Sava can hand to Dedal/operator.

### Owned files/folders

Allowed to modify/create:

```text
README.md
docs/DEPLOY.md
docs/OPERATIONS.md
docs/ENV.md
docs/TROUBLESHOOTING.md
```

Do not change Python code.

### Required docs

#### `docs/DEPLOY.md`

Must include:

- prerequisites for Ubuntu VPS;
- Docker install commands;
- first deploy with old folder parking;
- `.env` setup;
- startup commands;
- how to verify the bot is running;
- how to send a simple Telegram test.

#### `docs/OPERATIONS.md`

Must include:

- normal update;
- restart;
- stop/start;
- logs;
- backup DB;
- restore DB;
- rollback code;
- cleanup downloads/cache;
- how to check current git commit.

#### `docs/ENV.md`

Must include:

- every env var from `.env.example`;
- required vs optional;
- safe example values;
- where to get Telegram token;
- warning not to commit `.env`.

#### `docs/TROUBLESHOOTING.md`

Must include:

- Telegram token invalid;
- Postgres not healthy;
- migrations failed;
- YouTube cookies missing/stale;
- no space left on device;
- bot container restarts in loop;
- API key missing/rate-limited.

### Style

- Russian language.
- Assume reader is not a developer.
- Use copy-paste command blocks.
- Use warnings before destructive commands.
- Avoid vague phrases like "configure the server"; say exact commands.

### Verification

- Check all linked files exist.
- Check command blocks are internally consistent with Docker Compose service names.
- Check docs do not mention obsolete systemd/venv as the main production path.

---

## Task D — CI/Safety Gate Agent

### Goal

Add GitHub Actions checks so `main` is visibly deployable before pulling on VPS.

### Owned files/folders

Allowed to modify/create:

```text
.github/workflows/ci.yml
scripts/smoke-check.sh
requirements.txt
README.md
```

Do not change business logic unless needed to make imports/test setup deterministic.

### Required checks

Workflow on push and pull request:

1. checkout;
2. setup Python;
3. install system packages if needed for import checks;
4. install requirements;
5. run `pytest -q`;
6. run `python -m compileall .`;
7. run `scripts/smoke-check.sh`;
8. if Dockerfile/compose exists, run Docker build or at least `docker compose config`.

### Smoke check rules

- Must not call paid APIs.
- Must not download large media.
- Must not require real Telegram token.
- Should verify imports/config shape and basic parser/service behavior.

### Verification

Run locally if possible:

```bash
pytest -q
python -m compileall .
./scripts/smoke-check.sh
```

If Docker exists:

```bash
docker compose config
```

### Output report must include

- workflow triggers;
- checks included;
- any secrets required by CI, ideally none.

---

## Task E — Integration Reviewer

### Goal

Review DB + Docker + docs + CI together before merge/deploy.

### Review checklist

- Does `docs/DEPLOYMENT_ARCHITECTURE.md` still match the implementation?
- Does `.env.example` include every variable used by code/Compose/docs?
- Can a fresh VPS follow `docs/DEPLOY.md` without hidden steps?
- Does `docker compose up -d --build` start Postgres and bot?
- Do migrations run?
- Do tests pass?
- Is SQLite gone from production path?
- Are secrets excluded from Git?
- Are Obsidian/local paths owner-only and not public product defaults?
- Can callbacks/jobs survive restart if job persistence was implemented?
- Is rollback documented honestly, especially around DB migrations?

### Required output

```text
Verdict: APPROVED / REQUEST_CHANGES

Critical blockers:
- ...

Important issues:
- ...

Minor issues:
- ...

Commands run:
- ...
```
