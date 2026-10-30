## Deliverables

```yaml
- path: core/dashboard/data/spec_archive.py
  kind: modify
- path: tests/test_spec_archive_drain.py
  kind: new
```

## 1. 阈值饱和排水

- [ ] 1.1 core/dashboard/data/spec_archive.py：auto_archive_check（:630）触发条件由「计数 > archive.auto_threshold」改为「>= 即触发，单轮内按 updated 升序持续归档可归档条目直至终态目录计数低于阈值」；auto_threshold=0 仍为禁用。

## 2. 时效归档与孤儿接管

- [ ] 2.1 core/dashboard/data/spec_archive.py：新增时效归档——STATE 条目终态+目录含 verification-report.md+滞留超 3 天，即自动归档（不受 auto_threshold 约束）；复用既有 archive_spec 原子移动与归档台账。
- [ ] 2.2 core/dashboard/data/spec_archive.py：无 STATE 条目的孤儿目录（现存 2 例：evo-merge-back-wip-overlap-gate、fix-verify-loop-convergence）凡含 verification-report.md 且滞留超 3 天同规则归档（archived_by=auto-orphan）；不满足条件的孤儿仅入盘点清单。

## 3. 每日滞留盘点

- [ ] 3.1 core/dashboard/data/spec_archive.py：auto_archive_check 周期内加 24 小时去重的每日盘点——仍有含 verification-report.md 且滞留超 3 天的目录时列清单发 INFO 信号（复用 _archive_log 出口）。

## 4. 测试

- [ ] 4.1 tests/test_spec_archive_drain.py：覆盖 50/50 饱和态可触发归档、单轮排水至阈值下、时效归档 3 天边界（2 天不归档/3 天归档）、孤儿目录分流（有报告+超期归档/其余仅盘点）、STATE 非终态活跃目录与无报告目录不被误归档、auto_threshold=0 禁用语义不变。