# design — codefix-zero-face-regression-hardening

## 背景与实证

- 10-08 三批时间线（fenixd.log）：批 1（分支 fenix/code-review-fix-1791424850）02:36:45/03:10:15/03:44:37 三轮「回归未通过（timeout）」、04:18:32 三轮耗尽；批 2 同型至 06:40:58 耗尽；批 3 两轮 parse_error 后 07:40:32 熔断（「连续 2 次未产出可用失败明细」）。白天 10 份明细档 created_at 与各轮 run 时刻精确相差 1800 秒，证实批 1/2 每轮都烧满墙钟。
- 根因不在计数速度：`_is_regression_anomaly()`（core/code_fix.py:1048-1060）仅 status='parse_error' 或 status='failed' 且无 fail_items 为 True，timeout 恒 False，前两批从未进计数；daemon 于 10-08 04:18 重启（晚于 a26dbe88 02:14 合入，restart_history.jsonl），排除代码代差。

## 决策

1. **判据扩展优先于调参**：只把阈值 2→1 不解决 timeout 不进计数的问题；先补 `_is_regression_anomaly` 对 timeout-无明细的判定，anomaly 分档（跨链预算 1、一次性降档告警 `_write_anomaly_budget_alert`）即自动生效，重派侧零改动。
2. **首记收口按形态区分**：timeout 形态单轮固定烧 1800 秒墙钟且产不出任何证据，重试期望收益为负，首记即停；parse_error/failed 保留阈值 2（evo-add-codefix-anomaly-redispatch-budget 自述其为「防烧钱的保守兜底」，批 3 实践中也确在第二轮定位了形态）。实现取改动最小者：阈值按形态取值（timeout=1、其余=2，按形态查表），且**两个计数点都接判断**——首轮全量回归计数点（:5575-5583）计数后即短路（该处现无判断，:5573-5574 注释「阈值 ≥ 2 下首轮单次计数不可能达阈值，无需在此短路」随本次改判失效、须同步更新），定向轮计数点（:5667-5671）同款；timeout 形态触发时显式置 breaker_triggered/exhausted 再 break（for-else 语义：break 跳过 else 分支，exhausted 须手动置位，耗尽收口块与 reason 选择均依赖它）。
3. **证据留存取现成采集**：core/regression.py extract_long_tests（:274）已在 timeout/failed 路径把耗时超阈值用例写进快照 long_tests（本项目阈值 5s，.fenix/verify.yaml:120；代码缺省 8s，core/verify_contract.py:642），不新增采集逻辑；`_ingest_failure_round`（:1017-1037）现只读 snapshot['failures']，改为同时透传 long_tests；write_fix_reg_failures（:846）扩 schema 增可选键（向后兼容）；junit.xml.log 尾段（regression.py:863-873 逐用例进度日志）作为 long_tests 缺失时次选。快照与日志均在 exec_root=worktree（core/agent_runner/maintenance_runs.py:2300）且被 `_safe_cleanup`（code_fix.py:5800 调用）销毁，故必须在清理前并入明细档。
4. **1800 秒墙钟不调**：修后基线 8077 用例/449.59 秒（.fenix/regression/last-run.json，10-09 00:11），约 4 倍余量；条目「余量边缘」推断所依据的 20:56 零面实例实为 failed-映射不出形态（距 run 结束约 460 秒），与墙钟无关。verification 阶段复核并记录即可，.fenix/verify.yaml:99 的过时注释（5297 用例/254s）可顺带更新。

## 权衡

- timeout 首记即停放大偶发环境抖动的代价（一次抖动即停批），但该形态下继续重试是每轮 1800 秒的确定性烧钱且无证据产出，且跨链重派预算 1 已把后续收敛到 0-1 轮——取首记即停。
- 明细档 schema 扩展保持向后兼容（新增可选键），定向重试读 items、fallback_full 的既有路径不受影响。