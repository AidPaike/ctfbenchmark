# Droplet API 文档

本文档描述当前实现的 Droplet HTTP API。当前版本采用单机黑盒评测模型：没有多用户 session，也没有同题多副本 attempt；平台直接管理每道题目的服务生命周期。

## 基本信息

- 后端地址：`http://127.0.0.1:1349`
- 前端地址：`http://127.0.0.1:10349`
- 默认 Token：`droplet_dev_admin`
- 当前题目来源：`datasets/demo-xbow`
- 默认行为：后端启动时预启动全部题目服务

除 `GET /api/health` 外，接口都需要 Bearer Token：

```http
Authorization: Bearer droplet_dev_admin
```

开发环境中，`droplet_dev_admin` 和任意 `droplet_` 前缀 token 会被接受。

## Challenge 对象

Agent 可见的题目对象不会返回源码、Dockerfile、Compose、`.env` 或 flag。

```json
{
  "id": "xben-001-24",
  "title": "XBEN-001-24 IDOR - Trading Platform - Authorization",
  "description": "public task description",
  "category": "web",
  "task_type": "web_ctf_online",
  "dataset_id": "demo-xbow",
  "difficulty": "medium",
  "tags": ["idor"],
  "hint": "public hint",
  "judge_mode": "record_only",
  "status": "running",
  "target_url": "http://127.0.0.1:33027",
  "ports": [33027],
  "solved": false,
  "hint_viewed": false,
  "hint_penalty": 0.0,
  "submission_count": 0,
  "score": 0.0,
  "error_message": null,
  "started_at": "2026-05-28T10:00:00+00:00",
  "finished_at": null
}
```

状态：

- `not_started`：题目服务未运行
- `running`：题目服务已启动，Agent 可以通过端口访问
- `solved`：显式 checker / judge adapter 判定通过后的状态；当前 XBOW demo 不会自动进入该状态
- `error`：启动或运行失败

## 健康检查

### `GET /api/health`

无需认证。

```json
{
  "ok": true,
  "challenges": 5,
  "running": 5,
  "solved": 0,
  "prestart": {
    "total": 5,
    "started": ["xben-001-24"],
    "already_running": [],
    "errors": {},
    "running": 5
  }
}
```

## 原生接口

### `GET /api/challenges`

返回全部题目及其当前运行状态。

```bash
curl --noproxy 127.0.0.1 \
  -H "Authorization: Bearer droplet_dev_admin" \
  http://127.0.0.1:1349/api/challenges
```

响应：`Challenge[]`

### `GET /api/challenges/{challenge_id}`

返回单道题目的当前状态。

### `GET /api/events`

返回平台可见事件日志。可选查询参数：

- `challenge_id`：只看某道题
- `limit`：返回条数，默认 200，最大 1000

事件只记录平台能审计到的信息，例如题目加载、环境启动、启动失败、提示查看、提交记录、环境停止，以及 Agent 主动上报的摘要。不会记录隐藏思维链，也不会返回源码、flag 或提交原文。

### `GET /api/challenges/{challenge_id}/events`

返回单道题目的事件日志。

### `POST /api/challenges/{challenge_id}/events/clear`

清理前端活动链视图。该接口不会物理删除审计日志，只会在当前评测会话中把对应事件标记为 archived，后续列表接口不再展示。

```json
{
  "cleared": 12,
  "challenge_id": "xben-001-24"
}
```

### `POST /api/challenges/{challenge_id}/events`

外部 Agent 可主动上报一条可审计事件，用于前端活动链展示。

请求：

```json
{
  "event_type": "agent_event",
  "message": "used curl to inspect /login",
  "level": "info",
  "data": {"tool": "curl"}
}
```

响应：`Event`。敏感字段名如 `answer`、`flag`、`token` 会被写入前自动脱敏。

### `POST /api/challenges/start-all`

启动全部题目服务。也可以只启动指定题目：

```json
{
  "challenge_ids": ["xben-001-24", "xben-002-24"]
}
```

响应：

```json
{
  "total": 2,
  "started": ["xben-001-24"],
  "already_running": ["xben-002-24"],
  "errors": {},
  "running": 2
}
```

### `POST /api/challenges/stop-all`

停止全部正在运行的题目服务。

```json
{
  "stopped": ["xben-001-24"],
  "errors": {}
}
```

### `POST /api/challenges/{challenge_id}/start`

启动单道题目的真实 Docker Compose 服务，返回更新后的 `Challenge`。如果该题已经在运行，会先停止旧服务，再重新启动。

### `POST /api/challenges/{challenge_id}/stop`

停止单道题目服务并清理 `data/work/challenges/{challenge_id}`。

### `POST /api/challenges/{challenge_id}/reset`

停止并重新启动单道题目服务。分数、提示使用、提交次数会保留。

### `POST /api/challenges/{challenge_id}/submit`

提交 Agent 找到的 flag。当前 XBOW demo 不配置平台判题器，Droplet 只记录提交，不读取 `.env` 或题目源码中的 flag。

请求：

```json
{
  "answer": "FLAG{...}"
}
```

响应：

```json
{
  "accepted": true,
  "judged": false,
  "correct": null,
  "score_before_hint_penalty": null,
  "score_after_hint_penalty": null,
  "submission_count": 1,
  "message": "submission recorded; no flag judge is configured"
}
```

提交后题目环境保持运行。只有后续接入显式 checker / judge adapter 时，平台才可以返回 `judged: true` 并更新 `solved`。

### `POST /api/challenges/{challenge_id}/hint`

获取提示。每次使用提示扣 0.1 分。

```json
{
  "hint_id": "hint-1",
  "content": "try another ID",
  "penalty": -0.1,
  "hint_penalty": -0.1
}
```

### `GET /api/stats`

返回当前整个平台的统计。

```json
{
  "total_challenges": 5,
  "solved": 0,
  "running": 5,
  "overall_score": 0.0
}
```

当前 XBOW demo 没有平台侧 judge，`solved` 不会因为提交接口自动增加。后续只有显式配置 checker / judge adapter 的题目才会把提交转成判定结果。

## 腾讯/XBOW 兼容接口

这组三个接口用于兼容类似 `tencent-cloud-hackathon-intelligent-pentest-competition-api-server` 的 Agent 接入方式。

### `GET /api/v1/challenges`

返回当前已经加载的题目。正常启动模式下，后端 startup 已经预启动题目服务，所以这里会直接返回端口。

```json
{
  "current_stage": "competition",
  "challenges": [
    {
      "challenge_code": "xben-001-24",
      "difficulty": "medium",
      "points": 300,
      "hint_viewed": false,
      "solved": false,
      "status": "running",
      "target_url": "http://127.0.0.1:33027",
      "error_message": null,
      "target_info": {
        "ip": "127.0.0.1",
        "port": [33027]
      }
    }
  ]
}
```

### `GET /api/v1/hint/{challenge_code}`

返回提示：

```json
{
  "hint_content": "try another ID",
  "penalty_points": 100,
  "first_use": true
}
```

### `POST /api/v1/answer`

提交答案：

```json
{
  "challenge_code": "xben-001-24",
  "answer": "FLAG{...}"
}
```

响应：

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

## 启动策略

默认策略是预启动全部题目服务：

```bash
./scripts/dev-backend.sh
```

正式开放给 Agent 前，建议管理员先运行一次预启动检查：

```bash
./scripts/prestart-challenges.sh
```

该命令会启动题目并检查每道题是否 `running` 且有端口；如果有任何题目失败，命令返回非 0，输出中会列出失败题目的 `id`、`status`、`target_url`、`ports` 和 `error_message`。这一步通过后，再让 Agent 获取 `/api/v1/challenges` 开始答题。

关闭预启动：

```bash
DROPLET_PRESTART_CHALLENGES=0 ./scripts/dev-backend.sh
```

只预启动部分题目：

```bash
DROPLET_PRESTART_IDS=xben-001-24,xben-002-24 ./scripts/dev-backend.sh
```

单道题 Docker Compose 启动超时默认是 300 秒，避免首次镜像构建过慢时被误杀。需要更长时间时可以继续调大：

```bash
DROPLET_COMPOSE_TIMEOUT_SECONDS=300 ./scripts/dev-backend.sh
```

默认启动命令是 `docker compose up -d`。如果镜像已经存在，会直接启动；如果镜像不存在，Compose 会按需构建。需要强制 rebuild 时，在启动后端前设置：

```bash
DROPLET_FORCE_REBUILD=1 ./scripts/dev-backend.sh
```

## 日志系统

Droplet 当前日志分两层：

- 事件日志：`logs/droplet-events.jsonl`，结构化 JSONL，供前端活动链和 API 查询使用。
- 运行态目录：`data/work/challenges/<challenge_id>/`，只保存当前题目服务启动所需的临时 Compose/Dockerfile 副本。

后续接入 LLM Gateway 或托管 Agent Runner 时，应继续向事件日志追加 `llm_request`、`llm_response_summary`、`tool_call`、`tool_result`、`runner_status` 等平台可见事件；不要尝试记录模型隐藏思维链。

## 运行时目录

题目模板只保留一份：

```text
datasets/demo-xbow/challenges/XBEN-001-24/
```

启动题目时生成运行态副本：

```text
data/work/challenges/xben-001-24/
```

停止后，运行态目录会被清理。平台不会修改 `datasets/` 下的原题文件。

旧版原型中的 `data/work/attempts/` 属于 session/attempt 设计残留；当前版本启动时会自动删除该目录。

## 前端约束

- 不展示源码路径、Compose 路径、`.env` 或 flag。
- 提交接口在没有显式 judge 时只展示"已记录"，不能暗示已经判定正确。
- 不伪造 LLM 成本、token、turns。
- 活动链为空时展示空状态。
- 环境启动失败时展示 `error_message`，并允许用户重试。
- 明暗主题都要保证三列布局不重叠。

## 页面结构

主页三列：

1. 左侧：Benchmark/题目列表。
2. 中间：题目详情、目标地址、启动/停止、提示、Flag 提交。
3. 右侧：LLM / Agent 活动链。

活动链目前读取平台事件日志，不展示伪造 token/cost。外部 Agent 的 LLM 轨迹只有在 Agent 主动上报或后续接入 LLM Gateway 后才可统计。
