# 引擎受理门行为探针装配纪律

<!-- knowledge: capability=engine-gate-probe-assembly rev=1
     sources=spec/changes/evo-add-repair-claim-fingerprint-gate,spec/knowledge/_inbox/done/engine-gate-probe-stub-worktree-manager.md -->

PMEngine 引擎受理门（修复申报受理等派发链闸门）的 fail-open 语义，以及为这些门写行为测试与验证探针时的装配纪律：门体把异常静默转成放行，装配缺陷会伪装成「应拒收却放行」，本页给出判别入口与强制装配口径。

## 规则

- **引擎门一律 fail-open**：门体判定异常 = 放行 + ERROR 留痕，门故障不得楔死 fix 链。由此推出排查纪律：门语义探针出现「应拒收却放行」时，先怀疑测试装配缺陷而非产品缺陷（门体无可见异常、产品代码审查无缺陷是常态面）；判别入口是 logger 的 error 调用记录（fail-open 的唯一留痕面），不是断言输出。
- **真实 PMEngine 探针 MUST 显式置 `engine.agent_runner.worktree_manager = None`**：`engine._read_implementer_result` 经 `_find_implementer_worktree` → `agent_runner.worktree_manager.find_implementer_worktree(spec)` 取数；装配 `agent_runner=MagicMock()` 时该链路返回 MagicMock（truthy）→ `.exists()` 真值 → `read_text()` 仍返回 MagicMock → `json.loads` 抛 TypeError → 被门体 fail-open 吞成放行。置 `None` 走项目根共享结果文件兜底的真实语义。
- **条件式义务零注入**：向既有任务书/修复段追加「义务行」类改动，义务生效条件不成立时（如无派单指纹基线）MUST 零注入——返回空串而非占位行。既有段落精确断言（`tests/test_inplace_bug_repair.py` 的修复段尾断言）是零变化锚点，无条件追加会被确定性抓住；这属设计意图（条件式义务）而非测试过紧，不得为过测试改成无条件注入。

## 代码锚点

- 主实现：`core/pm_engine/engine.py`（`_repair_claim_fingerprint_gate` 门体与尾部 fail-open except 分支；`_read_implementer_result` → `_find_implementer_worktree` 取数链）
- 单源符号：`core/pm_engine/family.py`（`_repair_claim_fingerprint_section` 无基线返回空串；`_inject_verify_fix_task` 义务行条件拼接）
- 守卫测试：`tests/test_repair_claim_fingerprint_gate.py`（`_GateBase.setUp` 的 `worktree_manager = None` 装配锚点）；`tests/test_inplace_bug_repair.py`（修复段尾精确断言零变化锚点）

## 溯源

- 2026-11-16 engine-gate-probe-stub-worktree-manager（spec/knowledge/_inbox/done/engine-gate-probe-stub-worktree-manager.md） — 新建本页：引擎门 fail-open 语义与「应拒收却放行」判别入口、探针装配 worktree_manager=None 强制口径、条件式义务零注入契约。
