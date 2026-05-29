# Droplet 当前设计文档

本文档记录当前 Droplet 的有效设计。旧版多用户/多副本运行模型已废弃；当前目标是先把单机黑盒自动渗透 benchmark 平台跑稳。

## 目标

Droplet 用于评测外部自动化渗透测试 Agent。平台负责：

- 发现和展示题目；
- 启动真实题目服务；
- 暴露目标端口；
- 接收提示请求和 Flag 提交；
- 记录提交；只有显式配置 checker / judge adapter 的题目才进行平台侧判定；
- 记录平台可见事件；
- 提供前端、HTTP API、SDK 和 MCP 接入。

Agent 负责：

- 获取题目列表；
- 访问 `target_url`；
- 使用自己的工具链做题；
- 提交 Flag；
- 可选上报关键行为摘要。

平台不提供渗透工具，不要求 Agent 使用平台工具，也不会暴露源码、Dockerfile、Compose、`.env` 或真实 Flag。当前 XBOW demo 不读取 `.env` 中的 FLAG。

XBOW 题目的 flag 由原题 Docker 环境自行生成或注入。Droplet 只读取 `benchmark.json`、`droplet.yaml`、README 和 Compose 中可公开的元数据，不读取题目源码、数据库或 `.env` 来判题。

## 核心抽象

### Challenge

一道逻辑题目。包含公开元数据、当前运行状态、端口、提示状态、提交次数和得分。

### Dataset Adapter

数据集发现适配器。当前内置 `xbow`，后续 Vulhub、DVWA、Pikachu、CyberBattleSim 等应通过新 adapter 接入，而不是把逻辑写进 `manager.py`。

### Runtime Copy

每道题启动时会从 `datasets/.../challenges/<id>/` 复制到 `data/work/challenges/<id>/`。这是题目服务运行态副本，不是多用户副本。

需要运行态副本的原因：

- 动态改 host 端口；
- 动态注入 Docker build proxy；
- 清理旧代理配置；
- 避免污染题目模板；
- 停止题目时可以直接删除运行态目录。

### Event Log

平台事件日志写入 SQLite 表 `events`，并通过 API 和前端活动链展示。`logs/droplet-events.jsonl` 只作为旧事件迁移来源保留。

当前事件包括：

- `challenges_loaded`
- `challenge_start_requested`
- `challenge_started`
- `challenge_start_failed`
- `challenge_stopped`
- `challenge_stopped_externally`
- `hint_viewed`
- `submission_recorded`
- `agent_event`

外部黑盒 Agent 的 LLM 内部轨迹不能被平台自动获取。后续如果需要更完整的 LLM 统计，应通过 LLM Gateway 或 Agent 主动 `report_event` 上报摘要。不要记录隐藏思维链。

## 启动策略

支持两种模式：

- 预启动：后端启动时启动题目服务，适合正式评测前管理员检查环境。
- 按需启动：后端只加载题目，管理员或 Agent 调 API 启动题目，适合调试。

当前 README 推荐流程：

1. `DROPLET_PRESTART_CHALLENGES=0 ./scripts/dev/dev-backend.sh`
2. `./scripts/ops/prestart-challenges.sh`
3. 题目全部 ready 后启动前端或开放给 Agent。

## 数据集扩展

新增数据集时应做三件事：

1. 在 `datasets/<dataset>/droplet.yaml` 中声明 `auto_discover`。
2. 在 `backend/droplet/datasets.py` 中实现对应 adapter。
3. 为 adapter 增加 discovery 测试，验证题目数量、公开字段、隐藏字段和端口推断。

`manager.py` 不应知道具体数据集内部结构。

## 代理策略

题目模板中不能写机器相关代理。平台只在运行态副本中注入代理 build args。

默认：

- `DROPLET_DOCKER_PROXY=http://192.168.3.67:7890`
- `DROPLET_DOCKER_NO_PROXY=127.0.0.1,localhost,::1,host.docker.internal,pypi.tuna.tsinghua.edu.cn`

`pypi.tuna.tsinghua.edu.cn` 在 `NO_PROXY` 里，因为部分题目需要代理访问 Debian archive，但 pip 访问清华源时应绕过代理。

## 测试分层

- `tests/unit/`：纯函数、adapter、事件日志、CLI、runtime 配置渲染。
- `tests/integration/`：FastAPI contract、SDK/API 端到端、真实 Docker smoke。

真实 Docker 测试默认跳过，需要显式设置 `DROPLET_RUN_DOCKER_E2E=1`。

## 当前不做

当前阶段不实现：

- 多用户隔离；
- 托管 Agent Runner；
- LLM Gateway；
- 排行榜官方策略；
- 多用户权限模型；
- 同一题多实例并发。

这些能力可以后续添加，但不能破坏当前黑盒协议。
