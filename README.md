# Droplet

Droplet 是一个用于评测自动化渗透测试 Agent 的黑盒 CTF Benchmark 平台。

- 后端：FastAPI + SQLite，端口 `1349`
- 前端：React + Vite，端口 `10349`
- SDK：Python 客户端 + CLI + MCP Server
- 默认 Token：`droplet_dev_admin`

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
export DROPLET_DOCKER_PROXY=http://192.168.3.67:7890
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

自动完成：镜像预热 → 启动题目 → 启动后端 → 启动前端。终端顶部显示预热进度。

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
./scripts/platform/stop.sh          # 停止全部
./scripts/ops/stop-challenges.sh    # 只停题目容器
./scripts/ops/clean-runtime.sh      # 清理运行态目录
```

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

当前 XBOW demo 返回 `judged: false`，平台只记录提交，不判题。

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

## 常用命令

```bash
# 列出题目
PYTHONPATH=backend:sdk python -m droplet_sdk.cli challenges

# 启动/停止单题
PYTHONPATH=backend:sdk python -m droplet_sdk.cli start xben-001-24
PYTHONPATH=backend:sdk python -m droplet_sdk.cli stop xben-001-24

# 提交答案
PYTHONPATH=backend:sdk python -m droplet_sdk.cli submit xben-001-24 'FLAG{...}'

# 预热镜像
PYTHONPATH=backend:sdk python -m droplet_sdk.cli prefetch

# 查看统计
PYTHONPATH=backend:sdk python -m droplet_sdk.cli stats

# 诊断环境
./scripts/ops/doctor.sh
```

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
sdk/droplet_sdk/               # SDK（client + CLI + MCP）
scripts/                       # 启动/停止/运维脚本
```
