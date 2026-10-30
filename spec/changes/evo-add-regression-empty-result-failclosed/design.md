# 设计：codefix-regression-guard

## 改动点

1. core/regression.py — 判定 fail-closed
   - 解析判定分支（:985-993）加不变式：returncode≠0 且 total=0 → 走 parse_error/infra 失败处置，不判 passed（主判据，覆盖一切「命令没跑成」形态，含本案 exit=4）。
   - 叠加新鲜度维度：拟判 passed 前 getmtime(junit.xml) 早于本次命令 started_at → 同 R1 处置。
   - 留痕复用 :1014-1020 的 WARNING 通道，注明触发形态（empty_result/stale_xml）。
2. core/code_fix.py — 定向 targets 消毒
   - :2356-2370 _is_test_path 排除 .pyc 与 __pycache__ 段；
   - :2447-2469 grep -rl 结果过滤 __pycache__ 命中；
   - :2582-2589 输入行过滤 # 前缀与不存在路径，过滤项 WARNING 留痕；
   - 替换点 :2343/:2509 消除 #{test_targets} 声明（.fenix/verify.yaml:126）替换后的 # 残留（替换时吞掉紧邻 # 或在替换值层规范化），不改 verify.yaml 本身。
3. tests/test_regression_execution.py — 契约用例：exit≠0＋total=0 不得 passed；陈旧 XML 不得采信。
4. tests/test_code_fix_affinity_batching.py — 消毒用例：# 前缀/__pycache__/不存在路径被过滤且留痕，合法 targets 行为不变。

## 数据流

触碰面映射 → targets 消毒（新增）→ 执行回归 → 判定守卫（新增：returncode∧total、mtime）→ passed 仅在命令真实执行且结果新鲜时成立 → 合回。

## 边界与权衡

- 主判据用「returncode≠0∧total=0」而非仅 mtime：worktree 已销毁场景下无法回溯 XML 来源，spawn 前 unlink（:862-872）对并发写入不完备，前者覆盖面更宽（对在案先例 a6e2fcc99c8a 形态同样兜底）。
- fail-closed 的代价是被杀批次走既有失败链路（salvage/重试），相对伪绿合回的空保证是正确取舍。
- 与在飞 evo-codefix-zero-face-regression-hardening（code_fix.py anomaly 治理）无代码路径冲突：本 SPEC 只动 regression.py 判定与定向 targets 构造。
