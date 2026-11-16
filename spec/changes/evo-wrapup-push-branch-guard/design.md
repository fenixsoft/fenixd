# Design: wrapup-push-branch-guard

## Context

分支解析已由 evo-add-push-git-env-precheck（commit `e25e6b4d0`，2026-11-16 落地）承载：`_resolve_push_target_branch()`（配置 `pm.push.target_branch` → `git symbolic-ref --short HEAD` → "main" 三级）已用于收尾推送（approve_push 推送段 `target_ref = self._resolve_push_target_branch()`）与归档收口（`_archive_auto_commit` 尾部 `_git_push_ref(self._resolve_push_target_branch())`）。本 SPEC 不重写该解析。

经查仍存在的缺口：`_git_push_ref` 成功判定仅 returncode==0，approve_push 以 `main_ok` 收口——Everything up-to-date 空转计成功、无告警（engine.py 全文无 up-to-date 分流）；SHA 比对机器（`_remote_branch_sha` ls-remote / `_local_branch_sha` rev-parse）只用于 feature 分支 best-effort 去重与 backfill 清痕；启动对账（rev-list 领先计数）不存在。遗留「main」表述与动态解析矛盾：approve_push docstring「git push origin main — 成功判据」、_archive_auto_commit 注释 `_git_push_ref ("main")`、日志 "(main-first)" 文案。cloud-phone 事件（检出 master，origin/main 缺 95 提交、7 次成功 5 次空转）：根因分支脱钩已由 e25e6b4d0 修复，缺口暴露面仍需对账兜底。

## Goals / Non-Goals

- Goals：成功=目标分支远端 tip 前进；空转告警；启动对账；既有分支解析回归守护 + stale 表述清理。
- Non-Goals：不重写/不替换 `_resolve_push_target_branch`（分支解析 capability 归 push-git-env-precheck，不引入第二解析路径）；不改推送时机/退避/凭证（在途 fix-push-credential-env-and-retry-rearm 明文不新增推送语义）；不改 fenix/* 分支去重逻辑；不做自动 force-push。

## Design

1. **分支解析守护**：不新增 `_integration_ref`；以行为级回归测试锁定「master 检出项目推送 master / main 检出项目行为不变」；清理 approve_push docstring、_archive_auto_commit 注释、"(main-first)" 日志文案中与动态解析矛盾的 stale "main" 表述；核对 backfill_push_residuals 的「本地 main vs 远端 main SHA 相等即清痕」兜底——非 main 检出项目上该兜底恒不相等、残留永不清理（同型静默缺口），按解析基分支同步语义。
2. **tip 断言**：推送前 ls-remote 取目标分支远端 tip（复用 `_remote_branch_sha`），推送后再取比对；未前进→按 up-to-date 处理：不标记 pushed、发单条告警（告警面复用现有 kind，带本地/远端 tip）；前进→现流程。N/A 短路（evo-add-push-git-env-precheck 1.2）保持前置，不受断言影响。
3. **对账**：daemon 启动路径（pm_engine 启动段）对本地解析基分支跑 `rev-list --count 远端..本地`，结果进启动日志与数据摘要面。
4. **pushed 门**：`main_ok` 数据源改为「tip 前进」结果，语义不变（推送成功才标 pushed）。
5. **测试**：临时仓库模拟 master 检出项目断言推送 master、up-to-date 告警、tip 前进收口、对账输出。

## Risks / Trade-offs

- 远端不可达时 ls-remote 失败：按现有推送失败路径处理（不新增语义）。
- up-to-date 语义：以「推送前后远端 tip 比对」为准，未前进只发单条空转告警、不计失败、不进退避——避免与既有指数退避机制耦合造成误升级。
- 与 fix-push-credential-env-and-retry-rearm 续推通道的交互：续推经 approve_push 既有入口，tip 断言自动继承；其「远端 SHA 去重」与本断言同源（ls-remote），无双重判定冲突。
- 基分支对账对怪异仓库形态（detached HEAD 等）的兜底：解析失败按既有 `_resolve_push_target_branch` 的 "main" 兜底口径对账并日志注明。

## Migration

无数据迁移；对 master 检出项目即时生效（tip 断言使空转不再伪装成功，首次真实推送即暴露缺口）；origin/main 历史缺口由启动对账暴露后人工决定是否对齐。
