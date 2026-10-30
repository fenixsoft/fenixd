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

- [ ] 2.1 core/dashboard/data/spec_archive.py：新增时效归档——STATE 条目终态+目录含 verification-report.md+滞留 ≥ 3 天（目录 mtime，72 小时），即自动归档（archived_by=auto，不受 auto_threshold 约束）；复用既有 archive_spec 原子移动与归档台账。
- [ ] 2.2 core/dashboard/data/spec_archive.py：archive_spec 增加孤儿形态入参（allow_unregistered：跳过 STATE 成员查找与终态防御校验，保留防穿越白名单、TOCTOU 回滚、归档台账、runs 产物清理、commit_archive_move 自动提交；不写 STATE/清单条目，见 design 决策 6）。无 STATE 条目的孤儿目录（现存 2 例：evo-merge-back-wip-overlap-gate、fix-verify-loop-convergence，评审实测均无 verification-report.md）凡含 verification-report.md 且目录 mtime 滞留 ≥ 3 天同规则归档（archived_by=auto-orphan）；不满足条件的孤儿仅入盘点清单（见 3.1）。

## 3. 每日滞留盘点

- [ ] 3.1 core/dashboard/data/spec_archive.py：auto_archive_check 周期内加 24 小时去重的每日盘点——changes/ 存在以下任一类目录时列清单发 INFO 信号（复用 _archive_log 出口 :585）：① 含 verification-report.md 且滞留 ≥ 3 天的目录；② STATE 无条目的孤儿目录（无条件列示）；③ STATE 终态但无 verification-report.md 的目录。

## 4. 测试

- [ ] 4.1 tests/test_spec_archive_drain.py：覆盖 50/50 饱和态可触发归档且排水至阈值下（50→49 归档 1 条）、时效归档 3 天边界（目录 mtime <72h 不归档 / ≥72h 归档，含 STATE 路径与孤儿路径）、孤儿目录分流（有报告+超期经孤儿形态入参归档且台账 archived_by=auto-orphan/其余仅盘点）、STATE 非终态活跃目录与无报告目录不被误归档、无报告终态目录与孤儿目录进入每日盘点清单、auto_threshold=0 禁用全部自动归档动作（backfill 与盘点信号不受约束）语义。