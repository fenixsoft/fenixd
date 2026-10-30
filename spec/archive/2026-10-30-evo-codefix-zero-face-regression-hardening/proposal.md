# codefix-zero-face-regression-hardening

## Why

2026-10-08 白天 code-fix 车道同一组 8 条目连烧 10 个 run（精确合计 12.8489 美元、10:06-15:40 约 5.6 小时零收敛），直接根因是 tests/test_run_stop_loss.py 自创建（cfe5a164，09-26）即带全局 subprocess.Popen 泄漏（844a3312 已根治测试本身）。但零失败面收口防线未按预期工作：evo-add-codefix-anomaly-redispatch-budget（a26dbe88）当日 02:14 已合入，前两批却各烧满 3 轮定向重试。核查（evolution run evo-1791477251）实锤真因：core/code_fix.py `_is_regression_anomaly()`（:1048-1060）只把 parse_error 与 failed-无明细判为异常，status='timeout' 恒为 False——前两批 6 轮全部 timeout（每轮恰好烧满 1800 秒墙钟，明细档 created_at 与 run 时刻精确相差 1800s），异常计数器从未起表；第 3 批因形态碰巧翻成 parse_error 才触发熔断。即 anomaly 分档（预算 1、一次性降档告警）对 timeout 形态完全失效。次要缺口：回归失败明细档在 total=0 时只写 items=[] + fallback_full=true，毒化源定位全靠根治提交事后自述——runner 侧其实已采集慢测试进度（core/regression.py extract_long_tests :274，timeout 路径 :952-957 写快照 long_tests），但 code-fix 侧 `_ingest_failure_round` 只读 failures 丢弃之，快照与 junit.xml.log 又落在 worktree 内、随 `_safe_cleanup` 物理销毁。

## What Changes

- core/code_fix.py `_is_regression_anomaly()`：把「timeout 且无可用失败用例明细」补入异常判定——timeout 形态零失败面自此进入 anomaly 分档（reg_form=anomaly、跨链重派预算 1、一次性降档告警自动生效，均无需改动）。
- core/code_fix.py：timeout 零失败面首记即收口——不再等 REGRESSION_ANOMALY_BREAKER_THRESHOLD（现为 2，:1045）连续计数，批内首记即提前终止本批定向重试（0-1 轮内停止）；parse_error/failed 形态维持既有阈值 2 不变。
- core/code_fix.py `_ingest_failure_round()`/`write_fix_reg_failures()`：明细档在 worktree 清理前并入快照 long_tests（超阈值用例名+耗时；缺失时次选 junit.xml.log 尾段），使 timeout/total=0 形态的明细档可直接定位毒化源；字段缺失容错，旧消费方（items/fallback_full）不受影响。
- 复核项（随本 spec 核实、预期不改行为）：.fenix/verify.yaml 回归 timeout_seconds=1800 当前余量（修后基线 8077 用例/449.59 秒，约 4 倍），在 verification 阶段记录结论即可。

## Impact

- Affected specs: code-fix-lane（新增能力：零失败面回归的判据补全与证据留存）
- Affected code:
  - core/code_fix.py：`_is_regression_anomaly`、批 worker 异常计数/短路段（:5561、:5671 一带）、`_ingest_failure_round`、`write_fix_reg_failures`
  - 复用不改：core/regression.py extract_long_tests（已采集）；anomaly 分档/跨链预算/一次性告警（a26dbe88 已落地）
- Tests:
  - tests/test_codefix_anomaly_redispatch_budget.py 扩展（timeout 判定、首记收口、parse_error 阈值不回归）
  - tests/test_code_fix.py 扩展（明细档 long_tests 留存与容错）
- 风险：低——timeout 首记即收口的代价是偶发单次环境抖动即停批，但该形态单轮固定烧 1800 秒墙钟且产不出任何证据，盲跑重试期望损失更大；明细档增可选键向后兼容。