# Droplet

Droplet 是一个用于评测自动化渗透测试 Agent 的黑盒 CTF Benchmark 平台。平台负责启动题目服务、暴露端口、展示公开元数据、记录 Agent 提交；Agent 只通过端口访问题目，用自己的工具链做题。

当前 XBOW 题目遵循原题机制：Docker 启动后题目自己部署数据库和 flag。Droplet 不读取 `.env`、源码或数据库中的真实 flag，也不会为了判题去扫描题目文件。除非后续某个数据集显式配置 checker / judge adapter，否则提交接口只记录提交，返回 `judged: false`。

当前 demo 内置 5 道 XBOW 题目：

- 数据集目录：`datasets/demo-xbow`
- 题目 ID：`xben-001-24` 到 `xben-005-24`
- 后端端口：`1349`
- 前端端口：`10349`
- 默认 API Token：`droplet_dev_admin`

## 0. 进入项目目录

```bash
cd /home/fanzhenye/Desktop/ctfbenchmark
```

## 1. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd frontend
npm install
cd ..
```

确认 Docker 可用：

```bash
docker info
docker compose version
```

## 2. 配置 Docker 代理

当前默认代理是 `192.168.3.67:7890`。后端启动脚本会把这个代理注入到题目的运行态副本，不会修改 `datasets/` 下的原题文件。
默认 `NO_PROXY` 包含 `pypi.tuna.tsinghua.edu.cn`：部分老题目需要代理访问 Debian archive，但 `pip` 访问清华源时需要绕过代理，否则可能出现 `ProxyError` 或 TLS 超时。

如果 Docker build 需要代理：

```bash
export DROPLET_DOCKER_PROXY=http://192.168.3.67:7890
```

如果你需要追加或覆盖 Docker build 的绕过列表：

```bash
export DROPLET_DOCKER_NO_PROXY=127.0.0.1,localhost,::1,host.docker.internal,pypi.tuna.tsinghua.edu.cn
```

如果要完全关闭 Droplet 的 Docker build 代理注入：

```bash
export DROPLET_DOCKER_PROXY=
```

如果 Docker daemon 拉基础镜像失败，再执行：

```bash
./scripts/setup/configure-docker-daemon-proxy.sh
```

## 3. 启动后端

推荐先用“调试模式”启动后端：只加载题目元数据，不在后端 startup 阶段自动启动题目。这样后端会很快起来，题目启动错误也可以通过单独命令排查。

终端 1：

```bash
DROPLET_PRESTART_CHALLENGES=0 ./scripts/dev/dev-backend.sh
```

看到下面类似输出表示后端已启动：

```text
Uvicorn running on http://127.0.0.1:1349
Application startup complete
```

检查后端：

```bash
curl --noproxy 127.0.0.1 -s http://127.0.0.1:1349/api/health
```

## 4. 预启动并检查题目

终端 2：

```bash
./scripts/ops/prestart-challenges.sh
```

这个命令会：

- 调用后端的 `POST /api/challenges/start-all`
- 启动所有题目的 Docker Compose 服务
- 检查每道题是否为 `running`
- 检查每道题是否有端口
- 有任何题失败时返回非 0

成功时会看到：

```json
{
  "ok": true,
  "ready_count": 5,
  "failed_count": 0
}
```

失败时会看到类似：

```json
{
  "ok": false,
  "failed": [
    {
      "id": "xben-004-24",
      "status": "error",
      "target_url": null,
      "ports": [],
      "error_message": "Docker Compose timed out ..."
    }
  ]
}
```

这时不要让 Agent 开始评测。先根据 `failed[*].error_message` 排查 Dockerfile、网络、代理、基础镜像或题目配置。修完后重新执行：

```bash
./scripts/ops/prestart-challenges.sh
```

只检查当前状态、不重新启动题目：

```bash
./scripts/ops/prestart-challenges.sh --no-start
```

只启动/检查指定题目：

```bash
./scripts/ops/prestart-challenges.sh --challenge-id xben-001-24
```

如果某道题构建很慢，可以调大超时。注意：`DROPLET_COMPOSE_TIMEOUT_SECONDS` 要在启动后端时设置。

终端 1：

```bash
DROPLET_PRESTART_CHALLENGES=0 DROPLET_COMPOSE_TIMEOUT_SECONDS=300 ./scripts/dev/dev-backend.sh
```

终端 2：

```bash
DROPLET_CLIENT_TIMEOUT=900 ./scripts/ops/prestart-challenges.sh
```

默认启动题目使用 `docker compose up -d`，与参考项目一致：已有镜像时不会每次强制 rebuild，缺失镜像时 Docker Compose 会按需构建。需要强制重新构建题目镜像时，再在启动后端前设置：

```bash
DROPLET_FORCE_REBUILD=1 DROPLET_PRESTART_CHALLENGES=0 ./scripts/dev/dev-backend.sh
```

## 5. 启动前端

只有题目预启动检查通过后，再启动前端给用户或你自己使用。

终端 3：

```bash
./scripts/dev/dev-frontend.sh
```

打开：

```text
http://127.0.0.1:10349
```

## 6. Agent 接入方式

Agent 推荐使用兼容接口，流程非常简单：

1. 获取题目列表和端口
2. 通过端口访问题目服务
3. 提交 Agent 找到的 flag

获取题目：

```bash
curl --noproxy 127.0.0.1 -s \
  -H "Authorization: Bearer droplet_dev_admin" \
  http://127.0.0.1:1349/api/v1/challenges
```

返回里重点看：

```json
{
  "challenge_code": "xben-001-24",
  "status": "running",
  "target_url": "http://127.0.0.1:59393",
  "target_info": {
    "ip": "127.0.0.1",
    "port": [59393]
  }
}
```

提交 flag：

```bash
curl --noproxy 127.0.0.1 -s \
  -H "Authorization: Bearer droplet_dev_admin" \
  -H "Content-Type: application/json" \
  -d '{"challenge_code":"xben-001-24","answer":"FLAG{...}"}' \
  http://127.0.0.1:1349/api/v1/answer
```

当前 XBOW demo 的提交响应示例：

```json
{
  "correct": false,
  "judged": false,
  "accepted": true,
  "earned_points": 0,
  "is_solved": false,
  "message": "submission recorded; no flag judge is configured"
}
```

这里的 `accepted: true` 表示平台已记录提交，不表示 flag 正确。`judged: false` 表示当前题目没有平台侧判题器。

## 7. 常用管理命令

列出题目：

```bash
PYTHONPATH=backend:sdk python -m droplet_sdk.cli challenges
```

启动全部题目：

```bash
PYTHONPATH=backend:sdk python -m droplet_sdk.cli --timeout 600 start-all
```

停止全部题目：

```bash
./scripts/ops/stop-challenges.sh
```

启动单题：

```bash
PYTHONPATH=backend:sdk python -m droplet_sdk.cli --timeout 600 start xben-001-24
```

停止单题：

```bash
PYTHONPATH=backend:sdk python -m droplet_sdk.cli stop xben-001-24
```

提交答案：

```bash
PYTHONPATH=backend:sdk python -m droplet_sdk.cli submit xben-001-24 'FLAG{...}'
```

查看统计：

```bash
PYTHONPATH=backend:sdk python -m droplet_sdk.cli stats
```

查看平台活动链事件：

```bash
PYTHONPATH=backend:sdk python -m droplet_sdk.cli events --challenge-id xben-001-24
```

Agent 主动上报一条可审计事件：

```bash
PYTHONPATH=backend:sdk python -m droplet_sdk.cli report-event xben-001-24 agent_event "curl /login"
```

诊断本机环境：

```bash
./scripts/ops/doctor.sh
```

## 8. 一键开发模式

如果 Docker 镜像已经构建稳定，也可以直接启动后端并让它自动预启动题目：

```bash
./scripts/dev/dev-backend.sh
```

这个模式适合日常使用；如果题目还在调试，建议用第 3 步的 `DROPLET_PRESTART_CHALLENGES=0` 模式。

## 9. 停止项目

先停止题目容器：

```bash
./scripts/ops/stop-challenges.sh
```

然后在后端和前端终端按 `Ctrl-C`。

如果需要手动清理运行态目录：

```bash
./scripts/ops/clean-runtime.sh
```

## 10. 测试

普通单元测试：

```bash
PYTHONPATH=backend:sdk python3 -m pytest -q
```

真实 Docker/API 烟测：

```bash
DROPLET_RUN_DOCKER_E2E=1 PYTHONPATH=backend:sdk python3 -m pytest tests/integration/test_api_docker_e2e.py -q -s
```

前端构建：

```bash
cd frontend
npm run build
cd ..
```

## 11. 目录说明

题目模板只保留一份：

```text
datasets/demo-xbow/challenges/XBEN-001-24/
```

启动题目时生成运行态副本：

```text
data/work/challenges/xben-001-24/
```

停止题目后，运行态目录会被清理。旧版 `data/work/attempts/` 会在后端启动时自动删除。

平台事件日志写入：

```text
logs/droplet-events.jsonl
```

前端右侧“LLM / Agent 活动链”读取这个结构化事件日志。外部黑盒 Agent 的内部 LLM 轨迹不会被平台自动捕获；如果需要展示关键步骤，Agent 可以调用 `report-event` 或 `POST /api/challenges/{id}/events` 主动上报摘要。
