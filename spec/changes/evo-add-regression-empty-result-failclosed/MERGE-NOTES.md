# 合并增量（2026-10-30 人工全量核查）

折叠条目：7507b0c3cff5、8eaf5fdd4fe7、a31a79d0f2cf、ef3b49f3298d（同根因第 1-4 窗记录）。

- 判据终裁（以此为准）：`returncode≠0 ∧ total=0` 不得判 passed；保留「XML 新鲜且 total>0 的收尾崩溃」既有豁免（regression.py:1037-1039 注释的自意豁免不动）。**junit-freshness 主判据已被证伪**：regression.py:889-899 有预清理、pytest usage error 也写新鲜 0 例 XML（日志 total=0 即证）。
- 复发计数口径统一为 30 次（10-04~10-29，fenixd.log retained：log.4=1＋log.3=24＋log=5），含 10-29T19:46:35Z/20:16:51Z 两条（8eaf「本窗零复发」被当夜证伪）。
- targets 消毒三处：code_fix.py:2481 `grep -rlE` 加 `-I` 与 `--exclude-dir=__pycache__`；:2389 tests/ 前缀放行 .pyc 修正；:2528 替换前过滤 `#` 前缀/.pyc/不存在路径并留痕。
- 测试落点：tests/test_regression_execution.py + tests/test_code_fix_affinity_batching.py 增补，无需新文件。
- 覆盖检查：在飞 evo-codefix-zero-face-regression-hardening 只枚举 parse_error/failed空/timeout空，passed 形态不进其通道；fix-codefix-mapping-dotted-file-poison 治失败明细映射——均不同通道，无重复。
