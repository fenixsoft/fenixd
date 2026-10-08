# add-codefix-mergeback-conflict-salvage

## 背景

2026-10-02T21:40:52Z，code-fix 链（code-fix-1790973719 加定向重试 code-fix-1790976572，rollup runs=2 turns=700 tool_uses=350）合回预演检出与 main 在 core/state_machine.py 语义冲突（.fenix/logs/fenixd.log:41920-41921），按既有设计整批现场即弃：分支 fenix/code-review-fix-1790973716（tip_sha 1db39735）入失败档案（.fenix/code-review/fix-failed.json，36 项），resolved=0。新链 21:41:57 释放失败档案重做，22:43:28 rollup resolved=36 核销同批条目——约 1 小时批处理算力双倍消耗。根因：批回归跑在 worktree 上（core/code_fix.py:4140）看不见 main 新提交，链生命周期内基线前移（冲突提交 749d3e88/3a9ff694 于 20:56-57Z 落地，冲突前 44 分钟），冲突在批末合回才首次暴露，检出即全弃。日志中「现场即弃」已 5 次（09-23 两次、09-24 两次、10-02 一次），另有 09-22 一次旧语义交人工。

## 目标

1. 合回真冲突整批即弃前插入一次定向救回：批分支 rebase 到当前基线（复用 resolve_base_branch）并重跑批回归，通过则重走合回；至多 1 次。
2. rebase 仍冲突时按 commit（组）粒度 cherry-pick 回收非冲突提交，仅仍冲突组对应条目入失败档案计 fail_count。
3. 救回发生在分支清理（_safe_cleanup）之前，分支引用全程可用；救回全过程留日志、终局单行汇总。

## 非目标

- 不改 wip_gate_blocked（主树未提交 WIP 预检）走 defer 零预算的既有路径。
- 不改 FAIL_RETRY_MAX 预算与 release_retryable_failed_batches 释放语义。
- 不要求条目级精确回收：当前契约 message 无结构化 item_id 段，归属以 commit 组粒度为准；契约仅做 body 结构化标注增强。
- 不处理上游 provider 瞬态类损失（另行目承载）。

## 验收

- 构造真冲突场景：rebase 后回归通过则整批合回、链不再 resolved=0 全弃；rebase 仍冲突则非冲突组被回收、冲突组条目入档案带 fail_count。
- 救回失败最终仍走整批入档案兜底，行为与现状兼容。
- wip_gate_blocked defer 路径回归不变。
- 冲突即弃链的 turns 重复消耗较基线下降（同型场景对比）。