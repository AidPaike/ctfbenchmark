# 工程审计摘要

> 审计日期: 2026-06-02
> 审计范围: Droplet 平台源码、SDK、前端、脚本、测试与文档。不包含题目目录 `datasets/*/challenges/**`。

## 当前状态

| 类别 | 状态 |
|------|------|
| 后端 API | FastAPI + SQLite，认证改为精确 Bearer token |
| Docker 生命周期 | 运行态按 `compose_project/work_dir` 管理，已解题环境仍可停止 |
| 前端 | TypeScript 类型检查通过 |
| SDK/CLI/MCP | 保持原有接口 |
| 数据预处理器 | 已纳入包发现和 CI lint 范围 |
| 测试 | 单元测试与轻量 integration 已统一运行；CI 纳入 API contract |
| 文档 | README/CLAUDE 与当前判题、预热、鉴权行为同步 |

## 已验证

```bash
PYTHONPATH=backend:sdk python -m pytest tests/unit tests/integration -q
python -m ruff check backend sdk datasets/preprocessor tests
python -m ruff format --check backend sdk datasets/preprocessor tests
cd frontend && npx tsc --noEmit
```

结果：

- `164 passed, 3 skipped`
- `ruff check`: 通过
- `ruff format --check`: 通过
- `frontend tsc --noEmit`: 通过

## 仍需关注

- `frontend/dist/` 是已跟踪构建产物，构建后会产生 hash 文件变更。建议后续决定是否继续提交 dist，或从版本库中移除并只保留源码构建。
- Docker E2E 和全量题目 smoke 测试需要显式 Docker 环境，默认 CI 不运行。
- `logs/droplet-events.jsonl` 已在 `.gitignore` 规则内但历史上被跟踪，后续可单独清理 Git 跟踪状态。
