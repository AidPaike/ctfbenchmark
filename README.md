# Droplet

Droplet 是一个用于评测自动化渗透测试 Agent 的黑盒 CTF Benchmark 平台。

- 后端：FastAPI + SQLite，端口 `1349`
- 前端：React + Vite，端口 `10349`
- SDK：MCP Server
- 默认 Token：`droplet_dev_admin`（可用 `DROPLET_API_TOKEN` 覆盖）

平台负责启动题目 Docker 环境、暴露端口、记录提交；Agent 只通过端口访问题目。

## 安装

```bash
cd /home/fanzhenye/Desktop/ctfbenchmark
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd frontend && npm install && cd ..
```

确认 Docker 可用：

```bash
docker info
docker compose version
```

## 配置

### Docker 代理（可选）

如果 Docker build 需要代理：

```bash
export DROPLET_DOCKER_PROXY=http://192.168.3.67:7893
```

默认 `NO_PROXY` 已包含 `pypi.tuna.tsinghua.edu.cn`，避免 pip 走代理出错。如需关闭代理注入：

```bash
export DROPLET_DOCKER_PROXY=
```

### 数据集

主配置文件 `droplet.yaml`（项目根目录）：

```yaml
schema_version: 2
datasets:
  - ./datasets/xbow/challenges
  - ./datasets/demo-xbow/challenges
```

每个挑战目录必须包含 `benchmark.json` 和 `docker-compose.yml`。

## 启动

### 一键启动（推荐）

```bash
./scripts/platform/start.sh
```

自动启动后端和前端；默认执行镜像预热但不自动预启动全部题目，避免一次性占用过多 Docker 资源。终端顶部显示预热进度。

如需启动时预启动题目：

```bash
DROPLET_PRESTART_CHALLENGES=1 ./scripts/platform/start.sh
```

### 开发模式

分步启动，适合调试：

```bash
# 终端 1：启动后端（不自动启动题目）
DROPLET_PRESTART_CHALLENGES=0 ./scripts/dev/dev-backend.sh

# 终端 2：预启动题目
./scripts/ops/prestart-challenges.sh

# 终端 3：启动前端
./scripts/dev/dev-frontend.sh
```

### 停止

```bash
./scripts/platform/stop.sh          # 停止通过 PID 文件记录的平台进程
./scripts/ops/stop-challenges.sh    # 只停题目容器
./scripts/ops/clean-runtime.sh      # 清理运行态目录
```

如果 PID 文件丢失，`stop.sh` 会按端口清理确认属于当前项目的 Droplet 孤儿进程；非 Droplet 进程只提示不杀。如需完全禁用端口兜底清理，可用 `DROPLET_STOP_BY_PORT=0 ./scripts/platform/stop.sh`。

## Agent 接入

获取题目和端口：

```bash
curl --noproxy 127.0.0.1 -s \
  -H "Authorization: Bearer droplet_dev_admin" \
  http://127.0.0.1:1349/api/v1/challenges
```

提交 flag：

```bash
curl --noproxy 127.0.0.1 -s \
  -H "Authorization: Bearer droplet_dev_admin" \
  -H "Content-Type: application/json" \
  -d '{"challenge_code":"xben-001-24","answer":"FLAG{...}"}' \
  http://127.0.0.1:1349/api/v1/answer
```

包含 `.env` 中 `FLAG` 且 `win_condition: flag` 的题目会进行精确匹配判题；未配置 Flag 的题目返回 `judged: false`，平台只记录提交。

## MCP 接入

安装：

```bash
pip install -e ".[mcp]"
```

Claude Code / Cursor / Cline 配置：

```json
{
  "mcpServers": {
    "droplet": {
      "command": "python",
      "args": ["-m", "droplet_sdk.mcp_server"],
      "env": {
        "DROPLET_BASE_URL": "http://127.0.0.1:1349",
        "DROPLET_API_TOKEN": "droplet_dev_admin"
      }
    }
  }
}
```

可用工具：`list_challenges`、`start_all_challenges`、`stop_all_challenges`、`start_challenge`、`stop_challenge`、`reset_challenge`、`submit_answer`、`view_hint`、`get_stats`、`list_events`、`report_event`、`prefetch_images`。

## 新题预处理

```bash
python -m datasets.preprocessor \
  --raw-path /path/to/raw/challenge \
  --output-dir datasets/drafts/my-suite \
  --challenge-id RAW-001
```

生成 `benchmark.json`、`docker-compose.yml`、README 草稿等。公开 metadata 默认带 `needs_review: true`，需人工确认后入库。

## 测试

```bash
# 单元测试
PYTHONPATH=backend:sdk python -m pytest tests/unit/ -v

# 轻量 API 契约测试（不需要 Docker）
PYTHONPATH=backend:sdk python -m pytest tests/integration/test_api_contract.py -v

# Docker 集成测试（需要 Docker）
DROPLET_RUN_DOCKER_E2E=1 PYTHONPATH=backend:sdk python -m pytest tests/integration/test_api_docker_e2e.py -v -s
```

## 目录结构

```
datasets/xbow/challenges/      # XBOW 题目模板
datasets/demo-xbow/challenges/ # Demo 题目模板
data/work/challenges/          # 运行态副本（启动时生成，停止后清理）
data/droplet.db                # SQLite 数据库
backend/droplet/               # 后端代码
frontend/src/                  # 前端代码（单文件 main.tsx）
sdk/droplet_sdk/               # SDK（MCP Server）
scripts/                       # 启动/停止/运维脚本
```
