## Deliverables

```yaml
- path: core/regression.py
  kind: modify
- path: core/code_fix.py
  kind: modify
- path: tests/test_regression_execution.py
  kind: modify
- path: tests/test_code_fix_affinity_batching.py
  kind: modify
```

## 1. 判定 fail-closed

- [x] 1.1 core/regression.py：解析判定分支（:1012-1036，拟判 passed 落在 :1017-1020）加不变式「returncode≠0 且 total=0 → 按 parse_error/infra 失败处理，不得判 passed」，留痕用 :1041-1047 同款 log.warning 通道并注明触发形态（empty_result）。
- [x] 1.2 core/regression.py：拟判 passed 前校验 junit.xml 的 mtime 不早于本次命令 started_at（now_iso 字符串，比较前转时间戳），不满足按 1.1 同类失败处置并留痕（stale_xml）；「XML 新鲜且 total>0 的收尾崩溃」既有豁免（:1037-1040）不动。

## 2. 定向 targets 消毒

- [x] 2.1 core/code_fix.py：targets 消毒落单点 producer——_map_fix_files_to_tests 返回前（或调用点 :4152 拿到 targets 后）过滤 # 前缀项、__pycache__/.pyc 路径与不存在路径并 WARNING 留痕；MUST 覆盖两条注入通道（cmd 替换 :2535/:2555 与 FENIX_TEST_TARGETS env 导出 :2577，调用点 :6167/:6331/:6570/:6713）——仅在 _apply_test_targets 或仅在 env 导出点过滤均不合格；:2473-2495 grep 反查加 -I 与 --exclude-dir=__pycache__；:2389 tests/ 前缀支排除 __pycache__ 段与 .pyc。
- [x] 2.2 core/code_fix.py：消除 #{test_targets} 声明哨兵在替换后残留进执行命令的 #（替换点 :2535/:2555；_cmd_has_test_targets :2499-2508 探测不受影响），不改 .fenix/verify.yaml 本身。

## 3. 契约测试

- [x] 3.1 tests/test_regression_execution.py：钉住「exit≠0＋total=0 不得 passed」（含 usage error exit=4 形态）与「mtime 早于 started_at 的陈旧 XML 不得采信」两个契约；「XML 新鲜且 total>0 的非零退出仍 passed」既有豁免不回归。
- [x] 3.2 tests/test_code_fix_affinity_batching.py：覆盖 targets 含 # 前缀、__pycache__/.pyc、不存在路径时被过滤且留痕，env 导出值与 cmd 替换同源消毒（毒化项不再经任一通道进入 pytest），合法 targets 判定行为不变。
