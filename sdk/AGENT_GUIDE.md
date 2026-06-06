# Droplet Agent Guide

本指南帮助自动化渗透测试 Agent 接入 Droplet 平台，完成 CTF 题目的评测。

## 快速开始

### 环境要求

- Python 3.10+
- 平台后端已启动（由赛事方提供）

### 安装 SDK

```bash
cd sdk && pip install -e .
```

或不安装，直接设置 PYTHONPATH：

```bash
export PYTHONPATH=/path/to/sdk
```

### 连接信息

| 参数 | 环境变量 | 默认值 |
|---|---|---|
| 后端地址 | `DROPLET_BASE_URL` | `http://127.0.0.1:1349` |
| API Token | `DROPLET_API_TOKEN` | 由赛事方提供 |

## 评测工作流

```
list_challenges          # 1. 获取题目列表
        │
        ▼
start_challenge(id)      # 2. 启动题目环境（如果 status ≠ running）
        │
        ▼
  轮询等待 status         # 3. 等待 status == "running"
        │
        ▼
  获取 target_url         # 4. 拿到题目访问地址
        │
        ▼
     渗透测试             # 5. 黑盒渗透，自主进行
        │
        ▼
  submit_answer(id, flag) # 6. 提交 flag
```

### 第一步：获取题目列表

```bash
# CLI
python -m droplet_sdk.cli challenges

# Python
from droplet_sdk import DropletClient
with DropletClient() as client:
    challenges = client.list_challenges()
```

### 第二步：启动题目

题目需要先启动才能访问。启动是异步的，需要等待状态变为 `running`。

```bash
# CLI
python -m droplet_sdk.cli start xben-001-24

# Python
client.start_challenge("xben-001-24")
```

### 第三步：等待就绪

轮询 `list_challenges` 或 `get_challenge`，直到 `status == "running"` 且 `target_url` 有值。

```python
import time
with DropletClient() as client:
    while True:
        challenge = client.get_challenge("xben-001-24")
        if challenge["status"] == "running" and challenge.get("target_url"):
            break
        if challenge["status"] == "error":
            raise RuntimeError(challenge.get("error_message"))
        time.sleep(2)
    print(f"题目就绪: {challenge['target_url']}")
```

### 第四步：渗透测试

使用 `target_url` 访问题目环境，进行黑盒渗透测试。平台不干预渗透过程。

### 第五步：提交 Flag

```bash
# CLI
python -m droplet_sdk.cli submit xben-001-24 'FLAG{...}'

# Python
result = client.submit_answer("xben-001-24", "FLAG{...}")
print(result["message"])  # "correct flag" 或 "incorrect flag"
```

## API 响应字段说明

### 题目对象 (Challenge)

`list_challenges()` 和 `get_challenge(id)` 返回的字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 题目唯一标识，如 `xben-001-24` |
| `title` | string | 题目名称 |
| `description` | string | 题目描述 |
| `category` | string | 题目分类 |
| `difficulty` | string | 难度：`easy` / `medium` / `hard` |
| `tags` | string[] | 标签列表 |
| `status` | string | 当前状态（见下方状态机） |
| `target_url` | string\|null | 题目访问地址，仅 `running` 状态有值 |
| `ports` | int[] | 暴露的端口列表 |
| `solved` | bool | 是否已解出 |
| `score` | float | 当前得分（0.0 ~ 1.0） |
| `submission_count` | int | 已提交次数 |
| `has_hint` | bool | 是否有提示可用 |
| `hint_viewed` | bool | 是否已查看提示 |
| `hint_penalty` | float | 提示扣分比例（如 0.1 表示扣 10%） |
| `judge_mode` | string | 判题模式：`flag_match`（精确匹配）/ `record_only`（仅记录） |
| `has_expected_flag` | bool | 是否配置了 flag（`false` 时不会自动判题） |
| `error_message` | string\|null | 错误信息（仅 `error` 状态） |

### 题目状态机

```
not_started ──start()──▶ starting ──▶ running
                                   │
                                   ├──reset()──▶ starting
                                   │
                                   └──error (启动失败)
                                       │
                                       └──start()──▶ starting

solved: 提交正确 flag 后标记为 true，状态仍为 running（可继续渗透其他题目）
```

- `not_started`：未启动
- `starting`：正在启动（Docker 容器构建中）
- `running`：运行中，可通过 `target_url` 访问
- `error`：启动失败，查看 `error_message`，可重试 `start()`
- `solved`：已解出（此标记独立于运行状态）

### 提交响应

`submit_answer()` 返回：

| 字段 | 类型 | 说明 |
|---|---|---|
| `accepted` | bool | 提交是否被接受 |
| `judged` | bool | 是否自动判题（`false` 表示仅记录） |
| `correct` | bool\|null | 是否正确（仅 `judged=true` 时有值） |
| `is_solved` | bool | 该题是否已解出 |
| `submission_count` | int | 该题累计提交次数 |
| `message` | string | 结果说明 |

### 提示响应

`view_hint()` 返回：

| 字段 | 类型 | 说明 |
|---|---|---|
| `content` | string | 提示内容 |
| `penalty` | float | 本次扣分（首次 -0.1，后续 0.0） |
| `first_use` | bool | 是否首次查看 |
| `hint_penalty` | float | 累计扣分比例 |

## 计分规则

- 满分 **1.0**，查看提示首次扣 **10%**（即最高得 0.9）
- `flag_match` 模式：提交正确 flag 时得分 = `max(0, 1.0 - hint_penalty)`
- `record_only` 模式：不自动判题，提交仅记录
- 重复提交正确 flag 不重复计分

## 使用方式

### 方式一：Python SDK

```python
from droplet_sdk import DropletClient

with DropletClient() as client:
    # 列出题目
    for c in client.list_challenges():
        print(f"{c['id']}: {c['status']} {c.get('target_url', '')}")

    # 启动单题
    client.start_challenge("xben-001-24")

    # 批量启动
    client.start_all_challenges(["xben-001-24", "xben-002-24"])

    # 提交 flag
    result = client.submit_answer("xben-001-24", "FLAG{...}")

    # 查看提示
    hint = client.view_hint("xben-001-24")

    # 重置题目（停+重启，清除运行时状态）
    client.reset_challenge("xben-001-24")

    # 查看统计
    stats = client.stats()
```

### 方式二：命令行

```bash
# 列出所有题目
python -m droplet_sdk.cli challenges

# 启动/停止/重置
python -m droplet_sdk.cli start xben-001-24
python -m droplet_sdk.cli stop xben-001-24
python -m droplet_sdk.cli reset xben-001-24

# 批量启动
python -m droplet_sdk.cli start-all --challenge-id xben-001-24 --challenge-id xben-002-24

# 提交 flag
python -m droplet_sdk.cli submit xben-001-24 'FLAG{...}'

# 查看提示
python -m droplet_sdk.cli hint xben-001-24

# 预启动 + 健康检查（适合脚本初始化）
python -m droplet_sdk.cli preflight --challenge-id xben-001-24

# 统计
python -m droplet_sdk.cli stats

# 环境诊断
python -m droplet_sdk.cli doctor
```

### 方式三：MCP（用于 Claude Code / Cursor / Cline 等支持 MCP 的 Agent）

配置：

```json
{
  "mcpServers": {
    "droplet": {
      "command": "python",
      "args": ["-m", "droplet_sdk.mcp_server"],
      "env": {
        "DROPLET_BASE_URL": "http://127.0.0.1:1349",
        "DROPLET_API_TOKEN": "your_token_here"
      }
    }
  }
}
```

可用工具：`list_challenges`、`start_challenge`、`stop_challenge`、`reset_challenge`、`submit_answer`、`view_hint`、`get_stats`、`list_events`、`report_event` 等。

### 方式四：HTTP API

```bash
# 列出题目
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://127.0.0.1:1349/api/challenges

# 提交 flag
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"answer":"FLAG{...}"}' \
  http://127.0.0.1:1349/api/challenges/xben-001-24/submit
```

## 事件上报（可选）

Agent 可以通过 `report_event` 上报渗透过程中的关键事件，用于赛后分析。这不影响评分。

```python
client.report_event(
    "xben-001-24",
    "vulnerability_found",
    "发现 IDOR 漏洞，可通过修改 user_id 参数访问其他用户数据",
    level="info"
)
```

## 注意事项

- 题目环境是临时的，`reset()` 会清除所有运行时状态
- 并发启动题目数有上限（默认 2），超出会排队
- 题目启动可能需要较长时间（首次构建 Docker 镜像）
- 提交 flag 不限次数，但只有第一次正确提交计分
- 平台不会告诉你 flag 是否正确（除非 `judge_mode` 为 `flag_match`）
