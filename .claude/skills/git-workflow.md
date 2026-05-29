# Git Workflow

Manage branch lifecycle for the project's lightweight dual-trunk model.

## Invocation

`/git-workflow <command> <description>`

Or in Chinese: `/git-workflow 功能 持久化状态`

## Commands

| Command (EN) | Command (CN) | Action | Base Branch | Merge Target |
|---|---|---|---|---|
| `feat` / `feature` | `功能` / `新功能` | Start feature development | `develop` | `develop` |
| `fix` / `bugfix` | `修复` / `修` | Fix a bug | `develop` | `develop` |
| `release` | `发布` / `版本` | Prepare a release | `develop` | `master` + `develop` |
| `hotfix` | `热修` / `紧急修复` | Emergency production fix | `master` | `master` + `develop` |
| `cleanup` | `清理` | Delete merged local/remote branches | - | - |

## Description Format

- **feat/fix/hotfix**: Use kebab-case description, e.g. `persistent-state`, `port-stability`
- **release**: Use semantic version, e.g. `0.5.0`, `1.2.3`

## Workflow

### Feature / Fix

1. Ensure working tree is clean (stash if needed)
2. Switch to `develop` and pull latest
3. Create branch `feat/<desc>` or `fix/<desc>` from `develop`
4. Push to remote with tracking
5. Report: branch created, ready for development

### Release

1. Ensure working tree is clean
2. Switch to `develop` and pull latest
3. Create branch `release/<version>` from `develop`
4. Remind: only version bumps and critical fixes on this branch
5. Report: branch created, next step is PR to `master`

### Hotfix

1. Ensure working tree is clean
2. Switch to `master` and pull latest
3. Create branch `hotfix/<desc>` from `master`
4. Report: branch created, next step is PR to both `master` and `develop`

### Cleanup

1. Delete local branches already merged into `develop` or `master`
2. Delete corresponding remote branches (except `master`, `develop`)
3. Prune stale remote refs
4. Report: branches cleaned up

## Examples

```
/git-workflow feat persistent-state
/git-workflow 功能 持久化状态

/git-workflow fix port-stability
/git-workflow 修复 端口竞争

/git-workflow release 0.5.0
/git-workflow 发布 0.5.0

/git-workflow hotfix critical-security-patch
/git-workflow 热修 安全补丁

/git-workflow cleanup
/git-workflow 清理
```

## Branch Model

```
master     ← stable, production-ready, tagged releases only
  │
develop    ← default branch, daily integration
  │
  ├─ feat/xxx    feature branches → merge to develop → delete
  ├─ fix/xxx     bugfix branches → merge to develop → delete
  ├─ release/x.x release branches → merge to master + develop → delete
  └─ hotfix/xxx  emergency fixes → merge to master + develop → delete
```

## Rules

- Never push directly to `master` or `develop`
- All changes go through PR with squash merge
- Delete feature/fix branches after merge
- Tag releases on `master` after merge
