# Droplet MCP 接入说明

Droplet 当前是单机黑盒评测平台：平台负责启动题目服务、返回目标端口、记录 Flag 提交；外部 Agent 使用自己的工具链做题。当前 XBOW demo 不读取题目 `.env` 或源码判题，提交响应中的 `judged: false` 表示没有配置平台侧判题器。当前版本没有多用户 session，也没有同题多副本 attempt；全局重置只使用内部 reset epoch 隐藏旧进度。

## 安装

```bash
cd /home/fanzhenye/Desktop/ctfbenchmark
pip install -e ".[mcp]"
```

## MCP 配置

Claude Code / Cursor / Cline 均可使用类似配置：

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

## 可用工具

| Tool | 作用 |
|---|---|
| `list_challenges` | 查看所有题目、状态和目标地址 |
| `start_all_challenges` | 预启动全部或指定题目环境 |
| `stop_all_challenges` | 停止全部运行中的题目环境 |
| `start_challenge` | 异步启动单道题目环境，随后轮询题目状态获取 `target_url` |
| `stop_challenge` | 停止单道题目环境 |
| `reset_challenge` | 重置单道题目环境 |
| `submit_answer` | 记录 Agent 提交的 Flag |
| `view_hint` | 查看提示，首次查看扣 0.1 分 |
| `get_stats` | 查看整体统计 |
| `list_events` | 查看平台可见事件日志 |
| `report_event` | Agent 主动上报一条可审计事件 |
| `get_compat_challenges` | 腾讯云比赛兼容接口：题目列表 |
| `get_compat_hint` | 腾讯云比赛兼容接口：提示 |
| `submit_compat_answer` | 腾讯云比赛兼容接口：提交答案 |

## Agent 工作流

```text
1. 调用 list_challenges 查看题目和已启动目标。
2. 如果目标没有启动，调用 start_challenge 或让平台预启动。
3. 访问 target_url，用自己的工具链渗透。
4. 发现 Flag 后调用 submit_answer；当前 XBOW demo 只记录提交，不自动判断正确性。
5. 可选：调用 report_event 上报关键工具调用摘要，便于前端活动链展示。
6. 调用 get_stats 查看当前进度。
```

注意：平台不会自动获得外部 Agent 的 LLM 内部轨迹。只有平台 API 事件、提交记录、提示使用、环境生命周期，以及 Agent 主动 `report_event` 的内容会进入活动链。
