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

- [ ] 1.1 core/regression.py：解析判定分支（:985-993）加不变式「returncode≠0 且 total=0 → 按 parse_error/infra 失败处理，不得判 passed」，留痕复用 :1014-1020 并注明触发形态。
- [ ] 1.2 core/regression.py：拟判 passed 前校验 junit.xml 的 mtime 不早于本次命令 started_at，不满足按 1.1 同类失败处置。

## 2. 定向 targets 消毒

- [ ] 2.1 core/code_fix.py：定向 targets 出入口过滤 # 前缀项、__pycache__/.pyc 路径与不存在路径（:2356-2370、:2447-2469、:2582-2589），被过滤项 WARNING 留痕。
- [ ] 2.2 core/code_fix.py：消除 #{test_targets} 声明哨兵在替换后残留进执行命令的 #（替换点 :2343/:2509），不改 .fenix/verify.yaml 本身。

## 3. 契约测试

- [ ] 3.1 tests/test_regression_execution.py：钉住「exit≠0＋total=0 不得 passed」与「mtime 早于 started_at 的陈旧 XML 不得采信」两个契约。
- [ ] 3.2 tests/test_code_fix_affinity_batching.py：覆盖 targets 含 # 前缀、__pycache__/.pyc、不存在路径时被过滤且留痕，合法 targets 判定行为不变。
