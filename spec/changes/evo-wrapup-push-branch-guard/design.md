# Design: wrapup-push-branch-guard

## Context

engine.py 收尾推送三处：:3446（收尾推送目标）、:3628（归档推送）、:3333 起（成功判定）与 :3512（done→pushed 门）；SHA 比对机器 :3290-3320（现用于 fenix/* 去重）；core/git_base_branch.py:122 已有 (main,master) 基分支探测单源。cloud-phone 事件：7 次成功 5 次空转、4 次拒绝、origin/main 缺 95 提交。

## Goals / Non-Goals

- Goals：推送目标=实际基分支；成功=tip 前进；空转告警；启动对账。
- Non-Goals：不改推送时机/退避/凭证（在途 fix-push-credential-env-and-retry-rearm 明文不新增推送语义）；不改 fenix/* 分支去重逻辑；不做自动 force-push。

## Design

1. **基分支选择**：engine.py 内封装 `_integration_ref(project)`——检出分支（git symbolic-ref HEAD 或 worktree 元数据），fallback 到 git_base_branch 探测；:3446/:3628 改用它。
2. **tip 断言**：推送前 ls-remote 取远端 tip（复用 :3290-3320 机器），推送后再取比对；未前进→按 up-to-date 处理：不标记 pushed、发单条告警（告警面复用现有 kind，带本地/远端 tip）；前进→现流程。
3. **对账**：daemon 启动路径（pm_engine 启动段）对本地基分支跑 rev-list --count 远端..本地，结果进启动日志与数据摘要面。
4. **pushed 门**：:3512 的 main_ok 数据源改为基分支推送结果，语义不变（推送成功才标 pushed）。
5. **测试**：临时仓库模拟 master 检出项目断言推送 master、up-to-date 告警、tip 前进收口、对账输出。

## Risks / Trade-offs

- 远端不可达时 ls-remote 失败：按现有推送失败路径处理（不新增语义）。
- 基分支探测对怪异仓库形态的兜底：探测失败回退检出分支再回退 main，逐级降级并日志注明。

## Migration

无数据迁移；对 master 检出项目即时生效（首次推送即把 95 提交缺口推上 origin/master 类分支；origin/main 的历史缺口由启动对账暴露后人工决定是否对齐）。