## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_codefix_digest_metrics.py
  kind: modify
```

## 1. 读取路径回退

- [x] 1.1 core/code_fix.py：_read_run_metrics（约 :471-497）读 run 归档改双路径——先顶层 .fenix/runs/<run_id>.jsonl，缺失回退 .fenix/runs/archive/<run_id>.jsonl（对齐 core/admin_monitor.py:3401-3405 _admin_run_file 先例）；归零语义收窄为两路径皆缺，fail-open 保留；同步更新 :135 处「逐 run 读 .fenix/runs/<run_id>.jsonl」注释与本函数 docstring 的单路径表述为双路径

## 2. 测试

- [ ] 2.1 tests/test_codefix_digest_metrics.py：新增「run 文件仅存于 .fenix/runs/archive/ 时链末批 rollup 仍计得真实 turns/工具数」场景（以本窗口形状为夹具：runs=2 与 runs=1 两组非零期望）
- [ ] 2.2 tests/test_codefix_digest_metrics.py：双缺失按零贡献且不炸链终局、顶层与归档副本并存时结果一致（取顶层）两组边界用例