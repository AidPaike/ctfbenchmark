# 前后端接口需求

## 页面结构

主页三列：

1. 左侧：Benchmark/题目列表。
2. 中间：题目详情、目标地址、启动/停止、提示、Flag 提交。
3. 右侧：LLM / Agent 活动链。

活动链目前读取平台事件日志，不展示伪造 token/cost。外部 Agent 的 LLM 轨迹只有在 Agent 主动上报或后续接入 LLM Gateway 后才可统计。

## 后端必须提供

- `GET /api/challenges`
- `GET /api/challenges/{id}`
- `POST /api/challenges/start-all`
- `POST /api/challenges/stop-all`
- `POST /api/challenges/{id}/start`
- `POST /api/challenges/{id}/stop`
- `POST /api/challenges/{id}/reset`
- `POST /api/challenges/{id}/submit`
- `POST /api/challenges/{id}/hint`
- `GET /api/events`
- `GET /api/challenges/{id}/events`
- `POST /api/challenges/{id}/events`
- `GET /api/stats`

## Event 字段

```json
{
  "id": "evt_xxx",
  "timestamp": "2026-05-28T10:00:00+00:00",
  "level": "info",
  "event_type": "challenge_started",
  "message": "题目环境启动完成",
  "challenge_id": "xben-001-24",
  "data": {"target_url": "http://127.0.0.1:33027"}
}
```

敏感字段名如 `answer`、`flag`、`token`、`secret` 必须脱敏。

## 前端约束

- 不展示源码路径、Compose 路径、`.env` 或 flag。
- 提交接口在没有显式 judge 时只展示“已记录”，不能暗示已经判定正确。
- 不伪造 LLM 成本、token、turns。
- 活动链为空时展示空状态。
- 环境启动失败时展示 `error_message`，并允许用户重试。
- 明暗主题都要保证三列布局不重叠。
