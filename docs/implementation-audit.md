# Droplet 实现审计

## 当前状态

Droplet 已经从旧原型收敛为单机黑盒题目环境平台。当前实现重点是：

- 后端启动真实 Docker Compose 题目服务；
- 前端展示题目、目标地址、提交记录和活动链；
- SDK/CLI/MCP 提供同一套题目生命周期接口；
- 事件日志通过 JSONL 落盘并可查询；
- 题目模板不被污染，端口和代理只写入运行态副本。

## 做得对的地方

- `DatasetLoader` 和 adapter 开始从 `manager.py` 中拆出，后续可以接入更多 benchmark。
- `EventStore` 提供了统一的审计日志接口。
- `data/work/challenges/<challenge_id>/` 是明确的运行态目录。
- `data/work/attempts/` 已作为旧目录自动清理。
- 前端活动链不再使用前端模拟数据，而是读取后端事件。

## 仍需补强

P0：

- 持久化 Challenge 状态和事件索引。
- 给 Docker Compose 增加 CPU/内存限制和更细的失败诊断。
- 为每个 dataset adapter 增加 discovery contract。

P1：

- 拆分前端 `main.tsx`，形成 `ChallengeSidebar`、`TaskDetail`、`ActivityRail` 等独立文件。
- 将 FastAPI startup/shutdown 迁移到 lifespan，消除 deprecation warning。
- 增加 `GET /api/challenges/{id}/logs` 或容器日志摘要接口。

P2：

- LLM Gateway 与成本/token 统计。
- 托管 Agent Runner。
- 排行榜与版本化评测报告。
