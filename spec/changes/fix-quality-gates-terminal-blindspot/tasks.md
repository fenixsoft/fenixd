# fix-quality-gates-terminal-blindspot 任务清单

## Deliverables

```yaml
- path: core/dashboard/data/quality_gates.py
  kind: modify
- path: tests/test_quality_gates_progress.py
  kind: modify
```

## 1. ocr 门 merge-back 指纹豁免（读侧）

- [ ] 1.1 `core/dashboard/data/quality_gates.py` 的 `_lane_fingerprint_ok` 增加 merge-back 豁免分支：当 `expected["merge_base"]` 与 `expected["head_commit"]` 均非空且相等（分支已完整合入主基线的构造性判据）时，跳过产物 `merge_base` 比对（`branch`/`head_commit` 全等校验保持在前、不受豁免影响）；分支未合入路径行为逐字节不变；docstring 同步补豁免语义与实证根因（merge-back 后 merge-base 前移到分支尖）
- [ ] 1.2 `tests/test_quality_gates_progress.py` 新增用例：①merge-back 形态（expected merge_base==head_commit、产物 merge_base 为旧基线且 branch/head 全等）→ completed 产物采信、code-review 门 passed；②head 前移（expected.head_commit ≠ 产物 head_commit）→ 产物拒采信、门 pending；③未合入形态（expected merge_base≠head_commit 且产物 merge_base 不等）→ 产物拒采信、门 pending；用例指纹注入嵌套 `fingerprint` 子对象形态（对齐 run_impl_ocr 写侧）

## 2. full-suite 门终态豁免（读侧）

- [ ] 2.1 `core/dashboard/data/quality_gates.py` 的 `_full_suite_status` 增加终态短路：`spec_status ∈ ("verified", "done", "pushed")` → 返回 `(skipped, 固定文案常量)`，文案常量（如 `_TERMINAL_EXEMPT_REASON = "SPEC 已终态，全量回归跟踪移交主树"`）模块级固化；短路置于框架产物源之前（豁免优先级最高）；`parse_quality_gates` 调用点透传 `entry` 的 status（函数签名扩展为接收 spec_status，既有非终态调用语义不变）；非终态（implemented/testing 等）数据源优先级①②③与逐字节行为不变
- [ ] 2.2 `tests/test_quality_gates_progress.py` 新增用例：①pushed + 产物指纹陈旧 + 无自查键 → skipped、detail 为固定文案、计入 done（`parse_quality_gates` 输出 done 含该项）；②pushed + 产物指纹恰好匹配（且产物 failed）→ 仍 skipped（豁免优先于产物）；③testing + 同等陈旧条件 → pending（非终态行为不变，守卫既有①②③优先级用例零改动通过）

## 3. 回归保障

- [ ] 3.1 全量跑 `tests/test_quality_gates_progress.py` 与 `tests/test_impl_selfcheck_model_probe.py` 零失败（既有用例不允许改动断言；如确需改动须在 `.fenix-run-result.json` 说明原因），确认非终态语义与 6 道门键集/顺序/done 计数契约无回归
