# Droplet 全面代码审计报告

**审计日期**: 2026-05-31
**审计范围**: 文件结构、可扩展性、功能完备性、老旧代码与文档
**测试状态**: ✅ 65/65 通过 | Lint ✅ | Format ✅

---

## 一、文件结构评审

### 1.1 整体结构 ✅ 优秀

```
backend/droplet/     — 7 个模块，职责清晰
sdk/droplet_sdk/     — 3 个模块（client, cli, mcp_server）
frontend/src/        — 单文件 React 应用 + 独立 CSS
datasets/            — 数据集 + 预处理器
scripts/             — 平台启动/停止/运维脚本
tests/               — 单元测试 + 集成测试
```

**评价**: 模块边界清晰，没有 god-module。`manager.py`（1238 行）虽然最大，但内部用注释分段（Public interface / Persistence / Docker lifecycle / Watchdog / Helpers），逻辑组织合理。

### 1.2 发现的问题

| # | 严重度 | 问题 | 修复状态 |
|---|--------|------|----------|
| 1 | 🔴 Critical | `datasets/preprocessor/__init__.py` 导入 `from .batch import BatchRunner`，但 `batch.py` 不存在 | ✅ 已修复 → `from .base import BatchRunner` |
| 2 | 🔴 Critical | `datasets/preprocessor/base/__init__.py` 导入 `from .base import BasePreprocessor`，但 `base/base.py` 不存在 | ✅ 已修复 → `from .preprocessor import BasePreprocessor` |
| 3 | 🔴 Critical | `datasets/preprocessor/xbow.py` 导入 `from .base.base import ...` | ✅ 已修复 → `from .base import ...` |
| 4 | ⚠️ Warning | `backend/droplet/manager.py` 中 `_free_port()` 函数（第 1065 行）已无调用方，是死代码 | ✅ 已移除 |

---

## 二、可扩展性评审

### 2.1 数据集适配器模式 ✅ 优秀

`datasets.py` 使用 `Protocol` 结构化子类型 + 字典注册表模式：
- 新增数据集格式只需实现 `DatasetAdapter` 协议
- `DatasetLoader.__init__` 接受 `adapters` 参数，支持注入
- 自动发现逻辑（`_auto_discover`）支持单数据集和多数据集两种模式

### 2.2 Manager 耦合度 ⚠️ 中等

`DropletManager` 承担了：
- 挑战生命周期管理（start/stop/reset）
- Docker Compose 操作
- 进度持久化
- 代理注入
- 端口管理
- 健康检查看门狗

**建议**: 未来可考虑拆分为 `ComposeManager`（Docker 操作）和 `ChallengeManager`（业务逻辑），但当前规模下可接受。

### 2.3 数据库抽象 ✅ 良好

- SQLModel 使用清晰，表结构与业务模型分离
- Session-based 逻辑重置设计优雅（不删数据，只增代次）
- 迁移机制（`_ensure_sqlite_columns`）处理 additive changes

### 2.4 API 设计 ✅ 良好

- REST 风格一致：`/api/challenges/{id}/start`、`/api/challenges/{id}/submit`
- 兼容路由（`/api/v1/...`）与原生路由分离
- 错误处理统一：`try/except → HTTPException`

### 2.5 SDK 可扩展性 ✅ 优秀

- `DropletClient` 数据类，方法与 API 端点一一对应
- CLI 使用 argparse 子命令，新增命令只需：(1) 添加子解析器 (2) 添加处理分支
- MCP server 每个工具独立函数，添加新工具只需 `@mcp.tool()` 装饰器

### 2.6 前端可扩展性 ⚠️ 中等

- 单文件 `main.tsx`（707 行）目前可管理
- 无路由、无状态库，添加新页面需要重构
- 组件拆分合理（`App`, `ActivityRail`, `StatsBand`, `ChallengeSidebar`）

**建议**: 超过 1000 行时考虑拆分为多文件组件。

---

## 三、功能完备性评审

### 3.1 TODO/FIXME/HACK 注释 ✅ 无

全文搜索未发现任何 `TODO`、`FIXME`、`HACK`、`XXX`、`TEMP` 注释。

### 3.2 测试覆盖 ✅ 良好

| 模块 | 有测试 | 备注 |
|------|--------|------|
| `manager.py` | ✅ | runtime, concurrency, persistence |
| `database.py` | ✅ | persistence, session isolation |
| `events.py` | ✅ | record, list, clear |
| `datasets.py` | ✅ | manifest, auto-discover |
| `logging_config.py` | ✅ | handler creation, level filtering |
| `models.py` | ✅ | via other tests |
| `cli.py` | ✅ | argument parsing |
| `app.py` | ⚠️ | 仅集成测试（需要 Docker） |
| `mcp_server.py` | ❌ | 无测试 |
| `preprocessor/` | ✅ | CLI 入口测试 |

### 3.3 硬编码值

| 位置 | 值 | 建议 |
|------|-----|------|
| `app.py:25` | `ADMIN_TOKEN = "droplet_dev_admin"` | 可接受（开发环境默认值） |
| `manager.py:37` | `DEFAULT_DOCKER_NO_PROXY` 包含清华镜像地址 | 可接受（中国开发者友好） |
| `app.py:63-64` | CORS origins 硬编码 | 可接受（仅限本地开发） |

### 3.4 脚本目录 ✅ 全部有效

| 脚本 | 状态 |
|------|------|
| `scripts/platform/start.sh` | ✅ 有效（版本号已修复） |
| `scripts/platform/stop.sh` | ✅ 有效 |
| `scripts/dev/dev-backend.sh` | ✅ 有效 |
| `scripts/dev/dev-frontend.sh` | ✅ 有效 |
| `scripts/ops/clean-runtime.sh` | ✅ 有效 |
| `scripts/ops/doctor.sh` | ✅ 有效 |
| `scripts/ops/prestart-challenges.sh` | ✅ 有效 |
| `scripts/ops/stop-challenges.sh` | ✅ 有效 |
| `scripts/setup/configure-docker-daemon-proxy.sh` | ✅ 有效 |
| `scripts/setup/prepull-images.sh` | ✅ 有效 |

---

## 四、老旧代码与文档评审

### 4.1 CLAUDE.md ✅ 已修复

| 问题 | 修复状态 |
|------|----------|
| `DROPLET_DATASET_ROOT` 默认值写 `datasets/demo-xbow`，实际为 `datasets` | ✅ 已修复 |
| CLI 子命令列表不完整 | ✅ 已补全 |

### 4.2 CONTRIBUTING.md ✅ 准确

- 分支模型描述与实际 git 历史一致
- `/git-workflow` skill 文件存在且内容匹配

### 4.3 版本号一致性 ✅ 已修复

| 文件 | 修复前 | 修复后 |
|------|--------|--------|
| `scripts/platform/start.sh` | `0.5.1` | `0.6.0` |
| `backend/droplet/__init__.py` | `0.6.0` | `0.6.0` |
| `backend/droplet/app.py` | `0.6.0` | `0.6.0` |

### 4.4 Python 代码风格 ✅ 良好

- 类型注解完整（`from __future__ import annotations`）
- Docstring 中英双语
- 无废弃模式（无 `%-formatting`、无 `dict()` 替代字面量）
- Enum 使用 `str, Enum` 模式，JSON 序列化友好

### 4.5 Shell 脚本 ✅ 良好

- 使用 `set -euo pipefail`（严格模式）
- 无废弃标志
- 信号处理和清理逻辑完整

### 4.6 前端代码 ✅ 良好

- 使用函数组件 + Hooks
- 无废弃 React 模式（无 `findDOMNode`、无字符串 refs）
- `useRef` 正确用于避免 stale closure（参见 commit `3c701c8`）

### 4.7 SDK API 一致性 ✅ 良好

- `DropletClient` 方法与后端端点完全对应
- 兼容 API（腾讯风格）在 client、CLI、MCP server 三处均有实现

---

## 五、本次修复汇总

| # | 文件 | 修改内容 |
|---|------|----------|
| 1 | `datasets/preprocessor/__init__.py` | 修复导入：`from .batch` → `from .base`；`from .base.base` → `from .base` |
| 2 | `datasets/preprocessor/base/__init__.py` | 重写导出：`from .preprocessor` + `from .runner` + `from .types` |
| 3 | `datasets/preprocessor/xbow.py` | 修复导入：`from .base.base` → `from .base` |
| 4 | `backend/droplet/manager.py` | 移除死代码 `_free_port()` 函数 |
| 5 | `scripts/platform/start.sh` | 版本号 `0.5.1` → `0.6.0` |
| 6 | `CLAUDE.md` | 修正 `DROPLET_DATASET_ROOT` 默认值文档；补全 CLI 子命令列表 |

---

## 六、可选改进（未来考虑）

| 优先级 | 建议 |
|--------|------|
| Low | 添加 `mcp_server.py` 单元测试 |
| Low | 前端超过 1000 行时拆分为多文件组件 |
| Low | Manager 拆分为 `ComposeManager` + `ChallengeManager` |
| Info | 添加 OAuth/JWT 认证替代硬编码 token |
| Info | 添加前端 loading 状态指示器 |
