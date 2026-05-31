# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Droplet is a black-box CTF benchmark platform for evaluating automated penetration-testing agents. It loads challenge metadata from datasets, spins up Docker Compose environments on demand, exposes ports to agents, records submissions, and persists challenge progress and audit events to SQLite.

- **Backend**: FastAPI + SQLModel (SQLite), port `1349`
- **Frontend**: React + Vite (single-file `main.tsx`), port `10349`
- **SDK**: Python client (`httpx`) + CLI + MCP server in `sdk/droplet_sdk/`
- **Default token**: `droplet_dev_admin`

## Common Commands

### Tests

```bash
# All unit tests (no Docker required)
PYTHONPATH=backend:sdk python -m pytest tests/unit/ -v

# Single test file
PYTHONPATH=backend:sdk python -m pytest tests/unit/test_persistence.py -v

# Single test
PYTHONPATH=backend:sdk python -m pytest tests/unit/test_persistence.py::test_persist_progress_writes_to_db -v

# Docker/API integration smoke test (requires Docker)
DROPLET_RUN_DOCKER_E2E=1 PYTHONPATH=backend:sdk python -m pytest tests/integration/test_api_docker_e2e.py -v -s
```

### Lint / Format

```bash
ruff check backend/ sdk/ tests/
ruff format backend/ sdk/ tests/
```

### Start / Stop Platform

```bash
# Full production-like start (backend + frontend + auto-start challenges)
./scripts/platform/start.sh

# Development: backend only, no auto-start (fastest startup)
DROPLET_PRESTART_CHALLENGES=0 ./scripts/dev/dev-backend.sh

# Development: frontend only
./scripts/dev/dev-frontend.sh

# Pre-start challenges after backend is up
./scripts/ops/prestart-challenges.sh

# Stop everything
./scripts/platform/stop.sh

# Stop only challenge containers
./scripts/ops/stop-challenges.sh

# Clean runtime work dirs
./scripts/ops/clean-runtime.sh

# Diagnose environment
./scripts/ops/doctor.sh
```

### SDK CLI

```bash
PYTHONPATH=backend:sdk python -m droplet_sdk.cli challenges
PYTHONPATH=backend:sdk python -m droplet_sdk.cli stats
PYTHONPATH=backend:sdk python -m droplet_sdk.cli --timeout 600 start-all
PYTHONPATH=backend:sdk python -m droplet_sdk.cli submit xben-001-24 'FLAG{...}'
PYTHONPATH=backend:sdk python -m droplet_sdk.cli report-event xben-001-24 agent_event "curl /login"
```

### Dataset Preprocessor

```bash
python -m datasets.preprocessor \
  --raw-path /path/to/raw/challenge \
  --output-dir datasets/drafts/my-suite \
  --challenge-id RAW-001
```

## Architecture

### Backend (`backend/droplet/`)

| File | Role |
|---|---|
| `app.py` | FastAPI entry. **Module-level singleton** `DropletManager` shared across all requests. Startup sequence: `setup_logging()` → `init_db()` → `migrate_jsonl_to_sqlite()` → `manager.load_tasks()`. |
| `manager.py` | Core orchestrator. Challenge lifecycle: discover → start (async bg thread) → health check → stop → score → cleanup. Copies templates from `datasets/` to `data/work/challenges/<id>/` before running Docker Compose; proxy injection and port rewriting mutate only the copy. |
| `models.py` | `Challenge` is a single Pydantic model with three field groups: **static metadata** (from dataset, never changes), **runtime state** (ephemeral, not persisted), and **submission state** (`solved`, `hint_viewed`, `submission_count`, `score`). `public()` strips sensitive fields before sending to the client. |
| `database.py` | SQLite + SQLModel. Database file anchored to repo root via `_PROJECT_ROOT`. `get_engine()` is cached per path; `reset_engine()` clears it. `reset_session_cache()` clears the cached `session_id`. |
| `events.py` | `EventStore` persists audit events. `record()` tags events with the current `session_id`; `list()` filters by active session only. |
| `datasets.py` | Pluggable dataset loader. Adapters register by `dataset_type` in a dict. Current adapter: XBOW. |
| `logging_config.py` | `setup_logging()` configures root logger with `ColorFormatter` (terminal) + `SQLiteLogHandler` (DB). Calls `init_db()` internally before creating the DB handler so `system_logs` table exists on first startup. |

### Database Schema

All tables live in a single SQLite file (`data/droplet.db` by default):

| Table | Purpose |
|---|---|
| `events` | Audit events. Has `session_id` for logical reset isolation. |
| `system_logs` | Structured application logs from `SQLiteLogHandler`. |
| `challenge_progress` | Per-challenge submission state (`solved`, `score`, `hint_penalty`, etc.) per session. Unique on `(challenge_id, session_id)`. |
| `submissions` | Every answer attempt with `correct`, `score_before`, `score_after`. |
| `app_state` | Key-value store. Key `current_session_id` tracks the active session. |

### Session-Based Logical Reset

- `AppState` stores `current_session_id` (default 1).
- `ChallengeProgress`, `Submission`, and `Event` all have a `session_id` column.
- `reset_all_challenges()` calls `increment_session_id()` → old data stays in the database but is hidden from all queries.
- `reset_challenge()` resets progress for a single challenge in the current session.

**Important**: `SQLModel.metadata.create_all()` only **creates** tables; it never alters existing ones. If you add a column to a model, existing databases will crash on startup. During development, delete the old DB (`rm data/droplet.db`) and let `init_db()` recreate it. For production, write explicit `ALTER TABLE` migration scripts.

### Frontend (`frontend/src/`)

- `main.tsx`: Single-file React app (no router, no state library). Polls `/api/challenges` every 3s. Activity rail queries `/api/challenges/{id}/events`. Global reset-all button with confirmation dialog.
- `styles.css`: All styling in one file. Light/dark themes via `data-theme` attribute on `<html>`. Uses CSS variables for colors.
- `vite.config.ts`: Standard Vite + React setup. Dev server binds to `127.0.0.1:10349`.

### SDK (`sdk/droplet_sdk/`)

- `client.py`: `DropletClient` dataclass wrapping `httpx.Client`. Bearer auth, retry logic, timeout config.
- `cli.py`: Command-line interface using the client. Subcommands: `doctor`, `serve`, `challenges`, `events`, `report-event`, `preflight`, `start-all`, `stop-all`, `start`, `stop`, `reset`, `submit`, `hint`, `stats`, `compat-challenges`, `compat-hint`, `compat-submit`.
- `mcp_server.py`: FastMCP server exposing platform operations as MCP tools.

### Dataset Configuration

项目根目录的 `droplet.yaml` 是主配置文件，使用简单路径列表：

```yaml
schema_version: 2
datasets:
  - ./datasets/xbow/challenges
  - ./datasets/demo-xbow/challenges
```

路径相对于项目根目录解析。`DatasetLoader` 按以下顺序查找配置：
1. 项目根目录 `droplet.yaml`（推荐）
2. `{DROPLET_DATASET_ROOT}/droplet.yaml`（向后兼容）
3. 自动发现（无配置文件时）

### Dataset Directory Structure

```
datasets/
  xbow/challenges/
    XBEN-001-24/
      benchmark.json        # 公开元数据
      docker-compose.yml    # 运行时配置
      README.md             # 描述（可选）
      app/                  # 源码
  demo-xbow/challenges/
    XBEN-001-24/
      ...
```

每个挑战目录必须包含 `benchmark.json` 和 `docker-compose.yml`。

## Key Design Decisions

- **Port allocation**: Docker picks host ports via `"0:container_port"` in docker-compose.yml. After `docker compose up`, actual ports are resolved with `docker compose port <service> <container_port>`. This eliminated the previous TOCTOU race where Python bound a socket, closed it, and Docker claimed the same port a moment later.
- **Challenge isolation**: Templates under `datasets/` are never mutated. Each challenge is copied to `data/work/challenges/<id>/` before Docker Compose runs. Proxy injection and port rewriting only touch the copy.
- **Concurrency limit**: `DEFAULT_MAX_CONCURRENT_ENVIRONMENTS = 2`. `start_challenge()` rejects if the active count (running + starting + stopping) is already at the limit.
- **Watchdog**: A background daemon thread (`_watchdog_loop`) polls every 10s. Detects containers killed externally AND services that are running but no longer reachable (crashed process inside container). Marks unreachable endpoints as `status=error`.
- **Auth**: `require_auth()` in `app.py` accepts the hardcoded token `droplet_dev_admin` OR any token starting with `droplet_`. No user management.
- **Logging order**: `setup_logging()` now calls `init_db()` internally before creating `SQLiteLogHandler`. This fixes the first-startup bug where early logs were lost because `system_logs` did not exist yet.

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `DROPLET_DATASET_ROOT` | `datasets` | Challenge dataset root (config lookup: root `droplet.yaml` first, then this dir) |
| `DROPLET_WORK_ROOT` | `data/work` | Runtime work directories |
| `DROPLET_PUBLIC_HOST` | `127.0.0.1` | Host exposed to agents |
| `DROPLET_DATABASE_PATH` | `data/droplet.db` | SQLite file path |
| `DROPLET_PRESTART_CHALLENGES` | `1` | Auto-start all on backend startup |
| `DROPLET_PREFETCH_IMAGES` | `1` | Pre-pull Docker images before starting challenges |
| `DROPLET_DOCKER_PROXY` | — | HTTP proxy injected into Docker builds |
| `DROPLET_DOCKER_NO_PROXY` | — | Proxy bypass list for Docker builds |
| `DROPLET_TARGET_READY_TIMEOUT` | `90` | Seconds to wait for endpoint health |
| `DROPLET_COMPOSE_TIMEOUT_SECONDS` | `300` | Seconds before `docker compose up` aborts |
| `DROPLET_MAX_CONCURRENT_ENVIRONMENTS` | `2` | Max simultaneous running challenges |
| `DROPLET_FORCE_REBUILD` | `0` | Pass `--build` to `docker compose up` |

## Branch Workflow

This project uses a lightweight dual-trunk model (documented in `CONTRIBUTING.md`):

- `develop` — default branch. All feature/fix PRs squash-merge here.
- `master` — stable, production-ready. Only `release/*` and `hotfix/*` merge here.
- `feat/<kebab-desc>` from `develop` → PR to `develop` → squash merge → delete branch.
- `fix/<kebab-desc>` from `develop` → PR to `develop` → squash merge → delete branch.
- `release/<semver>` from `develop` → PR to `master` + `develop` → tag on `master` → delete branch.
- `hotfix/<kebab-desc>` from `master` → PR to `master` + `develop` → tag on `master` → delete branch.

## Test Isolation

`tests/conftest.py` provides an `isolated_database` fixture (autouse=True) that:

1. Sets a unique `DROPLET_DATABASE_PATH` per test via `tmp_path`
2. Calls `reset_engine()` to clear the SQLAlchemy engine cache
3. Calls `reset_session_cache()` to clear the cached `session_id`

This ensures tests never share DB state or session state. The `EventStore` internally calls `init_db()` on instantiation, so tables exist even for tests that do not explicitly call it.
