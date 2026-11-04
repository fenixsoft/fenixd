## Deliverables

```yaml
- path: core/dashboard/data/spec_archive.py
  kind: modify
- path: tests/test_spec_archive_drain.py
  kind: modify
```

## 1. 移除 R2 时效归档终态分支

- [ ] 1.1 `_archive_aged_specs` 移除 R2 终态归档分支：STATE 有条目的终态目录不再进入时效归档（终态归档仅由 R1 阈值排水触发）；保留 R3 孤儿分支（STATE 无条目 + verification-report.md + 目录 mtime >= 72h → 孤儿形态归档，archived_by=auto-orphan，判据与入参不变）；函数 docstring 同步移除 R2 描述
- [ ] 1.2 `run_auto_archive` 主流程与返回结构同步：`age_archived`/`age_skipped` 键语义随 R2 移除调整（保留 `orphan_archived`），模块 docstring 与行内注释（R1-R5 编号描述段、threshold=0 语义「R1/R2/R3 全部禁用」→「R1/R3 全部禁用」、design 决策引用）逐处更新；grep 确认返回键无模块外消费方遗留

## 2. R4 盘点水位观测化

- [ ] 2.1 `_daily_stale_audit` ①③合并为终态水位观测：终态未归档目录计数非零时发一条 INFO 列示计数与最老终态目录滞留天数（不按单目录列示、不区分含/不含 verification-report.md）；② 孤儿目录无条件列示保留；24h 去重与纯信号零动作语义不变

## 3. 测试改造与回归

- [ ] 3.1 R2 用例反转为「不归档」断言：原 3 天边界用例（终态+报告+>=72h 归档）改写为「终态+报告+>=72h 且计数低于阈值 → 不被归档」（保留判据构造逻辑作回归锚，禁止只删不反）；<72h 用例相应更新语义
- [ ] 3.2 R3 孤儿用例保留回归：>=72h 孤儿归档（archived_by=auto-orphan、不写 STATE/清单条目）与 <72h 只入盘点两路径断言不变，终态目录不被 R3 误伤补断言
- [ ] 3.3 R4 用例更新水位观测语义（计数+龄期单条 INFO、24h 去重、孤儿列示、终态目录不再单列）；R1 阈值排水（>= 触发/升序/target 计算）与存量回填用例回归通过

## 4. 收尾自证

- [ ] 4.1 受影响测试族全绿（test_spec_archive_drain.py、test_spec_archive.py 及 grep 到的 run_auto_archive/aged 消费测试）+ `python3 -m compileall core/` 通过
