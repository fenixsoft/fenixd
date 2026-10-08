# add-codefix-severity-batch-gate

## 背景

potplayer-base 的每日 scheduled 全量代码评审连续多日在近乎固定的 4-5 个工具文件上产出纯 minor/info 级发现（近 4 轮 11/7/4/3 条、零 major），却逐日触发完整「实现分支修复→合并→收尾回归」流水线：13 个 fix 提交加 4 个 merge 提交，且前一日修复新增的代码成为次日评审对象，形成自我供料循环（bin/run_full_suite.py 信号路径连续 4 轮被审被修）。

回源核查确认根因是框架能力缺口：
- /root/fenixd/core/config.py 的 get_code_review_config（:2125）与 get_code_review_fix_config（:2216）无任何严重度门限或收敛判据键；
- /root/fenixd/core/code_review.py generate_fix_spec（:1422-1428）仅按 status==open 过滤候选，minor/info 与 major 同批进入修复流水线；
- /root/fenixd/core/code_fix.py _select_batch_order_key（:1917）选批仅按 first_seen_at 排序，severity 不参与。

## 目标

1. code-review-fix 车道支持发现分级处置：severity 达到门限（缺省 major）的发现保持当日处置，minor/info 延后累积至周批统一修复。
2. 门限可配置（admin.code_review_fix.min_immediate_severity / minor_batch_cadence），非法值回退缺省不抛错（沿既有 fail-open 范式）。
3. code_review.py 与 code_fix.py 应用同一规则，Dashboard 手工通道不可绕过同门。
4. 运维收尾：用户级配置 admin.code_review.scope 由 full 回拨为 window（增量收集与空窗跳过已由 admin_monitor 现有实现免费获得）。

## 非目标

- 不取消每日 scheduled 评审，也不做 vendored 范围收缩（evo-code-review-vendored-scope 在飞覆盖）。
- 不改评审运行时段（evo-codefix-night-quiet-window / add-code-review-run-at 已覆盖）。
- 不取消 minor/info 发现的记录与呈现，只收紧其修复节奏。
