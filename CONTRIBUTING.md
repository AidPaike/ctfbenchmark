# Contributing Guide

## Git Branch Model

本项目采用**轻量级双主干模型**（Lightweight Dual-Trunk）。

```
master          ← 稳定版本，永远可部署，只有 release 和 hotfix 能合并
  │
develop         ← 默认分支，日常开发集成
  │
  ├─ feat/xxx      新功能分支
  ├─ fix/xxx       Bug 修复分支
  ├─ release/x.x   版本发布分支
  └─ hotfix/xxx    线上紧急修复分支
```

### 分支职责

| 分支 | 来源 | 合并目标 | 生命周期 |
|---|---|---|---|
| `master` | - | - | 长期存在 |
| `develop` | `master` | - | 长期存在（默认分支）|
| `feat/<描述>` | `develop` | `develop` | 功能完成后删除 |
| `fix/<描述>` | `develop` | `develop` | 修复完成后删除 |
| `release/<版本>` | `develop` | `master` + `develop` | 发布完成后删除 |
| `hotfix/<描述>` | `master` | `master` + `develop` | 紧急修复后删除 |

### 工作流

#### 1. 开发新功能

```bash
# 从 develop 切出特性分支
git checkout develop
git pull origin develop
git checkout -b feat/your-feature-name

# 开发、提交
git add .
git commit -m "feat: 描述"
git push -u origin feat/your-feature-name

# 在 GitHub 提 PR，目标分支选 develop
# 测试通过后 squash 合并
```

#### 2. 修复 Bug

```bash
git checkout develop
git pull origin develop
git checkout -b fix/bug-description

# 修复、提交
git commit -m "fix: 描述"
git push -u origin fix/bug-description

# 提 PR 到 develop
```

#### 3. 发布版本

```bash
# 从 develop 切出 release 分支
git checkout develop
git checkout -b release/0.5.0

# 只做版本号更新、CHANGELOG、小修小补，不开发新功能

# 完成后合并到 master 并打 tag
git checkout master
git merge --no-ff release/0.5.0
git tag -a v0.5.0 -m "Release v0.5.0"
git push origin master --tags

# 同时合并回 develop
git checkout develop
git merge --no-ff release/0.5.0
git push origin develop

# 删除 release 分支
git branch -d release/0.5.0
git push origin --delete release/0.5.0
```

#### 4. 线上紧急修复

```bash
# 从 master 切出 hotfix 分支
git checkout master
git pull origin master
git checkout -b hotfix/critical-bug

# 修复后同时合并到 master 和 develop
git checkout master
git merge --no-ff hotfix/critical-bug
git tag -a v0.5.1 -m "Hotfix v0.5.1"
git push origin master --tags

git checkout develop
git merge --no-ff hotfix/critical-bug
git push origin develop

# 删除 hotfix 分支
git branch -d hotfix/critical-bug
git push origin --delete hotfix/critical-bug
```

## 提交信息规范

采用 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

```
<type>(<scope>): <subject>

[可选正文]

[可选脚注]
```

### Type 说明

| Type | 含义 |
|---|---|
| `feat` | 新功能 |
| `fix` | 修复 |
| `docs` | 文档变更 |
| `style` | 代码格式（不影响逻辑）|
| `refactor` | 重构 |
| `test` | 测试相关 |
| `chore` | 构建/工具/依赖变更 |

### 示例

```
feat: add challenge progress persistence to SQLite

fix: resolve port allocation race condition

docs: update API endpoint descriptions
test: add regression test for session isolation
```

## 分支命名规范

| 类型 | 命名格式 | 示例 |
|---|---|---|
| 功能 | `feat/<kebab-case-desc>` | `feat/persistent-state` |
| 修复 | `fix/<kebab-case-desc>` | `fix/port-stability` |
| 发布 | `release/<semver>` | `release/0.5.0` |
| 热修 | `hotfix/<kebab-case-desc>` | `hotfix/critical-bug` |

## PR 规范

1. **标题**：简洁描述变更，使用 Conventional Commits 格式
2. **正文**：
   - Summary：变更概述
   - Changes：具体修改点
   - Test Plan：测试方法和结果
3. **合并方式**：使用 Squash Merge，保持主干历史整洁
4. **合并后**：删除特性分支

## 自动化助手

使用 Claude Code 的 `/git-workflow` skill 快速管理分支：

```bash
/git-workflow feat persistent-state    # 创建功能分支
/git-workflow fix port-stability       # 创建修复分支
/git-workflow release 0.5.0            # 创建发布分支
/git-workflow hotfix security-patch    # 创建热修分支
/git-workflow cleanup                  # 清理已合并分支
```
