# spec-changes-archive-drain

## 背景与问题

spec/changes/ 现存 52 目录：48 个含 verification-report.md、50 个对应 .fenix/STATE.md 终态条目（全 pushed），但归档已冻结 6 天（最后一条自动归档 2026-10-15 06:28）。根因（已核实）：自动归档 auto_archive_check（core/dashboard/data/spec_archive.py:630，fenixd.py:1122-1124 每 300 秒调用）仅当「终态+目录在 changes/ 计数 > archive.auto_threshold（默认 50，core/config.py:3312-3328）」才触发，当前计数恰为 50 → 阈值饱和、恒不归档；另有 2 个孤儿目录（evo-merge-back-wip-overlap-gate、fix-verify-loop-convergence）不在 STATE，自动归档与 backfill 均不接管。

已发生实损：自进化 run evo-1792427246（1778.7 秒、136 轮）两处把已落地能力误判「在途」并据此推迟立项裁决（「spec 滞留 changes/ 未归档，同主题在途先观察效果」「同主题 evo-api-stall-signal-grading 在途未归档」）；滞留每多一天，后续每轮自进化都重复这一误判与人工核对成本。

## 目标

1. 消除阈值饱和冻结：达到阈值即触发归档并单轮排水至阈值之下。
2. 时效归档：终态+已验证+滞留超 3 天的目录自动归档，孤儿目录（STATE 无条目）含验证报告同规则接管。
3. 每日一次滞留盘点 INFO 信号兜底。

## 非目标

- 不改 spec 派发/审批/验证流程与 STATE 语义。
- 不归档无验证报告的活跃在途目录（正常工作面）。