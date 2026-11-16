# 引擎门行为探针的装配纪律：worktree_manager 桩与 fail-open 静默放行

## 背景

为 judge-repair-claim-gate（evo-add-repair-claim-fingerprint-gate）写引擎受理门
行为测试与验证探针时，以 `PMEngine(sm, MagicMock(), {}, root, logger)` 装配真实
PMEngine。「缺探针标注 → 应拒收」路径系统性返回 False（伪放行），门体无任何可见
异常，产品代码肉眼审查无缺陷。

## 结论（当前事实）

1. `PMEngine` 引擎门方法体一律 fail-open（异常 = 放行 + ERROR 留痕，门故障不得
   楔死 fix 链）。凡测试/探针装配缺陷触发的异常都被静默转成「放行」：门语义探针
   出现「应拒收却放行」时，先怀疑装配缺陷而非产品缺陷，判别入口是 logger 的
   error 调用记录，不是断言输出。
2. `engine._read_implementer_result` 经 `_find_implementer_worktree` →
   `agent_runner.worktree_manager.find_implementer_worktree(spec)` 取数。装配时
   `agent_runner=MagicMock()` 会让该调用返回 MagicMock（truthy）→ `.exists()`
   真值 → `read_text()` 返回 MagicMock → `json.loads` 抛 TypeError。装配真实
   PMEngine 做引擎门探针 MUST 显式置 `engine.agent_runner.worktree_manager = None`
   （走项目根共享结果文件兜底的真实语义）。
3. 向既有任务书/修复段「追加义务行」类改动：义务生效条件不成立（如无派单指纹
   基线）时 MUST 零注入（返回空串而非占位行）。既有段落精确断言（如
   test_inplace_bug_repair 的修复段尾断言）是零变化锚点，无条件追加会被确定性
   抓住——这是设计意图（条件式义务）而非测试过紧。

## 证据

- 复现：`PMEngine` + MagicMock agent_runner 下调用
  `engine._repair_claim_fingerprint_gate(parent, fix)` 返回 False，逐步展开门体
  定位到 `_read_implementer_result` 抛
  `TypeError: the JSON object must be str, bytes or bytearray, not MagicMock`。
- 修复锚点：`tests/test_repair_claim_fingerprint_gate.py` `_GateBase.setUp` 的
  `worktree_manager = None` 注释段。
- 产品侧 fail-open 语义：`core/pm_engine/engine.py`
  `_repair_claim_fingerprint_gate` 尾部 except 分支（ERROR 留痕 + return False）。
- 零注入锚点：`core/pm_engine/family.py` `_repair_claim_fingerprint_section`
  （无基线返回空串）与 `_inject_verify_fix_task`（`_fp_lines` 条件拼接）。

建议落域：implementer-lane（引擎门测试装配纪律）。
