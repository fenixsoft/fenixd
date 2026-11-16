# Proposal: wrapup-push-branch-guard

## Why

cloud-phone 事故（检出分支 master）：旧代码收尾推送硬编码 `_git_push_ref("main")`，推送目标与工作落地分支脱钩——7 次「Main push succeeded」中 5 次为 up-to-date 空转（origin/main tracking ref 11-09 16:21 后零更新）、4 次被远端 non-fast-forward 拒绝；STATE.md 8 个 spec 全标 pushed 与「origin/main 缺 95 提交」并存，pushed 状态不再证明交付可达远端，windows-desktop-client 全套交付一度仅存本地。

> **事实基线更新（spec-review 评审实测，2026-11-16）**：上述「分支脱钩」根因已由 evo-add-push-git-env-precheck（commit `e25e6b4d0`，2026-11-16 23:12 落地）修复——收尾（approve_push 推送段）与归档收口（_archive_auto_commit 尾部）推送目标均已改经 `_resolve_push_target_branch()` 动态解析（配置 `pm.push.target_branch` → 检出分支 → main 三级），「硬编码 main」在当前 HEAD 已不存在，分支解析 capability 归 push-git-env-precheck 所有。本 SPEC MUST NOT 重写/替换该解析（不引入第二解析路径），对该目标转为**行为级回归守护**。

经查仍真实存在的缺口（本 SPEC 的实际标的）：

1. **成功判据仅 returncode==0**：`_git_push_ref` 以 push 子进程退出码论成败，approve_push 以 `main_ok` 收口——`Everything up-to-date` 空转与真实 tip 前进不可区分，空转照旧计成功、无任何告警（engine.py 全文无 up-to-date 分流）。
2. **目标分支推送无 tip 前进断言**：SHA 比对机器（`_remote_branch_sha` ls-remote / `_local_branch_sha` rev-parse）已存在，但只服务于 feature 分支 best-effort 去重与 backfill 清痕，目标分支推送主路径不用它。
3. **无启动对账**：engine.py 全文无 rev-list/领先计数——判据失明期的静默缺口（如 cloud-phone 的 95 提交悬置）无任何暴露面。

## What Changes

- **tip 前进断言与空转告警（core/pm_engine/engine.py）**：目标分支推送成功判定从 returncode==0 升级为「远端 tip 前进」断言（复用既有 SHA 比对机器）；Everything up-to-date 空转不再计成功并发单条告警。
- **分支解析回归守护与 stale 表述清理（core/pm_engine/engine.py）**：不重写 `_resolve_push_target_branch`；清理与其动态解析矛盾的遗留「main」表述（approve_push docstring「git push origin main — 成功判据」、_archive_auto_commit 注释 `_git_push_ref ("main")`、日志 "(main-first)" 文案），并核对 backfill_push_residuals 的「本地 main vs 远端 main」清痕兜底是否需同步基分支语义。
- **启动对账**：daemon 启动时对账本地基分支相对远端的领先提交数并上报，兜住判据失明期的静默缺口。
- **单测**：覆盖推送目标解析守护、tip 断言、空转告警、对账上报。

## Capabilities

### delivery-push-integrity

见 specs/delivery-push-integrity/spec.md。

## Impact

- core/pm_engine/engine.py 收尾推送路径（成功判定、pushed 门数据源）与归档收口推送判定；分支解析机制（`_resolve_push_target_branch`）仅守护不重写。
- core/git_base_branch.py 不在改动面（推送目标解析已由 e25e6b4d0 的检出分支机制承载，不再引入基分支探测第二路径）。
- 与在途 fix-push-credential-env-and-retry-rearm 范围互斥保持：其续推通道经 approve_push 既有入口复用语义，tip 断言落地后续推自动继承，无需其改动；其 spec 明文不新增推送语义。
- 不改变推送时机、退避与凭证处理。
