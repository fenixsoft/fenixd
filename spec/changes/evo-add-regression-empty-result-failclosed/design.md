# 设计：codefix-regression-guard

## 改动点

1. core/regression.py — 判定 fail-closed
   - 解析判定分支（:1012-1036，拟判 passed 落在 :1017-1020）加不变式：returncode≠0 且 total=0 → 走 parse_error/infra 失败处置，不判 passed（主判据，覆盖一切「命令没跑成」形态，含本案 exit=4 与零收集 exit=5）。
   - 叠加新鲜度维度：拟判 passed 前 getmtime(junit.xml) 早于本次命令 started_at → 同 R1 处置，覆盖 :889-899 预清理 unlink OSError 被吞（:893-894）后遗留旧 XML 被采信的残余洞；started_at 为 now_iso 字符串，比较前转时间戳。
   - 留痕复用 :1041-1047 同款 log.warning 通道（regression 组件），注明触发形态（empty_result/stale_xml）；「XML 新鲜且 total>0 的收尾崩溃」既有豁免（:1037-1040 注释）保留不动。
2. core/code_fix.py — 定向 targets 消毒
   - 消毒落点 MUST 为单点 producer：_map_fix_files_to_tests 返回前，或调用点 :4152 拿到 targets 后即刻过滤——targets 同时流向 _apply_test_targets 的 cmd 替换（:2535/:2555）与第三返回值经 :6167/:6331/:6570/:6713 的 _with_test_targets_env 环境变量导出（:2577）。只在 _apply_test_targets 内（MERGE-NOTES 曾拟 :2528）或只在 env 导出点过滤，都会给另一条通道留毒化面；本案实测肇因通道即 env 注入（fenixd.log.3:35219）。
   - 过滤规则：# 前缀项、路径含 __pycache__ 段、.pyc 文件、相对 exec_root 不存在的路径；被过滤项 WARNING 留痕（含原因）。消毒后空集 → 沿用既有 fail-open 回退全量（:4162-4166），不以空 targets 起跑。
   - :2382-2396 _is_test_path 排除 __pycache__ 段与 .pyc（:2389 tests/ 前缀支现在先于一切判别返回 True）；:2473-2495 grep -rlE 加 -I 与 --exclude-dir=__pycache__。
   - 替换点 :2535/:2555 消除 #{test_targets} 声明（.fenix/verify.yaml:126）替换后的 # 残留（替换时吞掉紧邻 # 或在替换值层规范化；_cmd_has_test_targets :2499-2508 的探测先于替换、不受影响），不改 verify.yaml 本身。
3. tests/test_regression_execution.py — 契约用例：exit≠0＋total=0 不得 passed（含 usage error 形态）；陈旧 XML 不得采信。
4. tests/test_code_fix_affinity_batching.py — 消毒用例：# 前缀/__pycache__/.pyc/不存在路径被过滤且留痕，env 导出值与 cmd 替换同源消毒，合法 targets 行为不变。

## 数据流

触碰面映射 → targets 消毒（新增，单点 producer，cmd+env 双通道共享）→ 执行回归 → 判定守卫（新增：returncode∧total、mtime）→ passed 仅在命令真实执行、结果新鲜且 total>0 时成立 → 合回。

## 边界与权衡

- 主判据用「returncode≠0∧total=0」而非仅 mtime：pytest usage error 也落新鲜 0 例 XML（MERGE-NOTES 终裁、fenixd.log.3:35220 total=0 即证），mtime 判据对本案形态不触发；worktree 已销毁场景下无法回溯 XML 来源，spawn 前预清理（:889-899）对 unlink 失败/并发写入不完备，前者覆盖面更宽（对在案先例 a6e2fcc99c8a 形态同样兜底）。
- fail-closed 的代价是被杀批次走既有失败链路（parse_error 进既有 anomaly 计数/salvage/重试），相对伪绿合回的空保证是正确取舍；合法 targets 全为零收集文件（conftest/helpers 类）时 rc=5+total=0 同判，属明示收紧而非回归。
- 与在飞 evo-codefix-zero-face-regression-hardening 无代码路径冲突：该 SPEC 动 code_fix.py _is_regression_anomaly/worker 异常短路段与 _ingest_failure_round 明细档，本 SPEC 动 regression.py 判定与定向 targets 构造（:2382-2595、:4152 一带）；R1 产出的 parse_error 恰好落入其保留阈值 2 的 parse_error 通道，语义互补。
