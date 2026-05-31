# CLAUDE.md

本文件为 Claude Code 提供项目开发指引。

## 项目概述

Droplet 是黑盒 CTF Benchmark 平台，用于评测自动化渗透测试 Agent。加载题目元数据 → 启动 Docker Compose 环境 → 暴露端口 → 记录提交 → 持久化到 SQLite。

## 常用命令

```bash
# 单元测试
PYTHONPATH=backend:sdk python -m pytest tests/unit/ -v

# 单个测试
PYTHONPATH=backend:sdk python -m pytest tests/unit/test_persistence.py::test_fn -v

# Lint / Format
ruff check backend/ sdk/ tests/
ruff format backend/ sdk/ tests/

# 一键启动（含镜像预热）
./scripts/platform/start.sh

# 开发模式：后端不自动启动题目
DROPLET_PRESTART_CHALLENGES=0 ./scripts/dev/dev-backend.sh

# 预启动题目
./scripts/ops/prestart-challenges.sh

# 停止
./scripts/platform/stop.sh

# SDK CLI
PYTHONPATH=backend:sdk python -m droplet_sdk.cli challenges
PYTHONPATH=backend:sdk python -m droplet_sdk.cli submit xben-001-24 'FLAG{...}'

# 新题预处理
python -m datasets.preprocessor --raw-path /path/to/raw --output-dir datasets/drafts/my-suite --challenge-id RAW-001
```

## 架构

### 后端 `backend/droplet/`

| 文件 | 职责 |
|---|---|
| `app.py` | FastAPI 入口。模块级单例 `DropletManager`。启动流程：`setup_logging()` → `init_db()` → `migrate_jsonl_to_sqlite()` → `manager.load_tasks()` → 后台线程执行镜像预热 + 预启动。 |
| `manager.py` | 核心编排。生命周期：发现 → 预热镜像 → 启动（异步） → 健康检查 → 停止 → 清理。模板从 `datasets/` 复制到 `data/work/challenges/<id>/` 再运行 Docker Compose。 |
| `models.py` | `Challenge` 模型，三组字段：静态元数据、运行时状态、提交状态。`public()` 脱敏。 |
| `database.py` | SQLite + SQLModel。`get_engine()` 按路径缓存，`reset_engine()` 清除。 |
| `events.py` | `EventStore` 审计事件。`record()` 标记 `session_id`，`list()` 按活跃 session 过滤。 |
| `datasets.py` | 可插拔数据集加载器。适配器按 `dataset_type` 注册。支持 `droplet.yaml` 配置和自动发现。 |
| `logging_config.py` | `setup_logging()` 配置 `ColorFormatter`（终端）+ `SQLiteLogHandler`（DB）。 |

### 前端 `frontend/src/`

- `main.tsx`：单文件 React 应用，无路由，无状态库。3s 轮询 `/api/challenges`。
- `styles.css`：全部样式，`data-theme` 切换明暗主题。

### SDK `sdk/droplet_sdk/`

- `client.py`：`DropletClient`，httpx 封装。
- `cli.py`：argparse 子命令。
- `mcp_server.py`：FastMCP 工具集。

### 数据库表

SQLite 文件：`data/droplet.db`

| 表 | 用途 |
|---|---|
| `events` | 审计事件，带 `session_id` |
| `system_logs` | 结构化应用日志 |
| `challenge_progress` | 每题提交状态（`solved`、`score` 等），按 session 隔离 |
| `submissions` | 每次提交记录 |
| `app_state` | KV 存储，`current_session_id` 跟踪活跃 session |

### Session 逻辑重置

`AppState` 存储 `current_session_id`。`reset_all_challenges()` 递增 session ID，旧数据保留但对查询不可见。

**注意**：`SQLModel.metadata.create_all()` 只建表不改表。新增字段需删库重建（开发）或写 `ALTER TABLE` 迁移（生产）。

## 关键设计

- **端口分配**：Docker 通过 `"0:container_port"` 随机分配宿主端口，`docker compose port` 解析实际端口。
- **题目隔离**：`datasets/` 模板不被修改。每题复制到 `data/work/` 再运行。代理注入和端口改写只动副本。
- **并发限制**：`DEFAULT_MAX_CONCURRENT_ENVIRONMENTS = 2`。
- **看门狗**：后台线程 10s 轮询，检测容器外部杀死或服务不可达。
- **镜像预热**：`prefetch_images()` 后台线程执行 `docker compose pull`，只拉镜像不启动容器。
- **认证**：`require_auth()` 接受 `droplet_dev_admin` 或 `droplet_` 前缀 token。

## 环境变量

| 变量 | 默认值 | 用途 |
|---|---|---|
| `DROPLET_DATASET_ROOT` | `datasets` | 数据集根目录 |
| `DROPLET_WORK_ROOT` | `data/work` | 运行态目录 |
| `DROPLET_PUBLIC_HOST` | `127.0.0.1` | 暴露给 Agent 的主机 |
| `DROPLET_DATABASE_PATH` | `data/droplet.db` | SQLite 路径 |
| `DROPLET_PRESTART_CHALLENGES` | `1` | 启动时自动开始所有题目 |
| `DROPLET_PREFETCH_IMAGES` | `1` | 启动时预热 Docker 镜像 |
| `DROPLET_DOCKER_PROXY` | — | Docker build 代理 |
| `DROPLET_DOCKER_NO_PROXY` | — | 代理绕过列表 |
| `DROPLET_TARGET_READY_TIMEOUT` | `90` | 端口健康检查超时（秒）|
| `DROPLET_COMPOSE_TIMEOUT_SECONDS` | `300` | `docker compose up` 超时 |
| `DROPLET_MAX_CONCURRENT_ENVIRONMENTS` | `2` | 最大并发运行题目数 |
| `DROPLET_FORCE_REBUILD` | `0` | 强制 `--build` |

## 分支模型

双主干：

- `develop`：默认分支，功能/修复 PR squash 合并到这里
- `master`：稳定版本，只有 `release/*` 和 `hotfix/*` 合并

命名：`feat/<描述>`、`fix/<描述>`、`release/<版本>`、`hotfix/<描述>`

## 测试隔离

`tests/conftest.py` 的 `isolated_database` fixture（autouse=True）：

1. `tmp_path` 设置独立 `DROPLET_DATABASE_PATH`
2. `reset_engine()` 清除 SQLAlchemy 缓存
3. `reset_session_cache()` 清除 session ID 缓存

## 数据集配置

`droplet.yaml`（项目根目录）：

```yaml
schema_version: 2
datasets:
  - ./datasets/xbow/challenges
  - ./datasets/demo-xbow/challenges
```

查找顺序：根目录 `droplet.yaml` → `{DROPLET_DATASET_ROOT}/droplet.yaml` → 自动发现。

目录结构：

```
datasets/
  xbow/challenges/
    XBEN-001-24/
      benchmark.json        # 公开元数据
      docker-compose.yml    # 运行时配置
      README.md             # 描述（可选）
      app/                  # 源码
```
