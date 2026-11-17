## Deliverables

```yaml
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_wrapup_push_branch_guard.py
  kind: new
```

> 行号锚点说明：engine.py 处于高频并发改动中，下述「约 :NNNN」以撰写时点为准，实现时以符号检索为准。

## 1. tip 前进断言与 stale 表述清理

- [x] 1.1 core/pm_engine/engine.py：清理与 `_resolve_push_target_branch` 动态解析矛盾的遗留「main」表述（approve_push docstring「git push origin main — 成功判据」、_archive_auto_commit 注释 `_git_push_ref ("main")`、日志 "(main-first)" 文案）；核对 backfill_push_residuals（约 :4310 起）的「本地 main vs 远端 main SHA 相等即清痕」兜底在非 main 检出项目上的行为并同步基分支语义；MUST NOT 重写/替换 `_resolve_push_target_branch`（分支解析归 push-git-env-precheck capability）
- [x] 1.2 core/pm_engine/engine.py：目标分支推送成功判定（approve_push 推送段 `main_ok` 收口，约 :3691 区域）升级为远端 tip 前进断言（推送前后 `_remote_branch_sha` 比对），Everything up-to-date 空转不计成功并发单条告警（带本地/远端 tip）；N/A 短路保持前置；pushed 门数据源同改

## 2. 启动对账

- [x] 2.1 core/pm_engine/engine.py：daemon 启动路径对本地解析基分支相对远端的领先提交数对账并输出（rev-list --count），供日志与聚合面消费

## 3. 测试

- [x] 3.1 tests/test_wrapup_push_branch_guard.py：覆盖「master 检出项目推送目标为 master（既有 `_resolve_push_target_branch` 解析回归守护）」「空转推送不标 pushed 且告警单条」「tip 前进正常收口」「启动对账输出领先数」四场景
