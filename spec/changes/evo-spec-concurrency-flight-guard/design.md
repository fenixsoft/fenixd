# Design: spec-concurrency-flight-guard

## D1: 审核收尾回退守卫（spec_review.py）

core/pm_engine/spec_review.py 收口处（consume_review_result，约 :283）：

```python
current = self._pm.state_machine.read_one(spec_name) or {}
if current.get("status") in ("implementing", "implemented", "testing"):
    self.logger.info("spec_review", f"评审收尾遇在飞实现 run（status={current.get(\"status\")}），跳过回退: {spec_name}")
    return  # 不回退 implementing→ready
# 否则维持既有回退（implementing→ready / reviewing→ready）
```

幂等：status 非 implementing 时走既有路径。in-flight 记录：日志级别 INFO（不是 ERROR），语义「评审结论已落盘但不改在飞实现状态」。

## D2: 派发前在飞评审校验（engine.py）

engine.py `_on_spec_ready` 派发 implementer 前：

1. 读 spec 记录：status 或 run 表中是否存在 spec-review-*/repair-* run 且状态在飞（非终态）
2. 有 → 跳过本次派发（INFO 日志「在飞评审 run，派发顺延: {run_id}」），等待 review 收尾事件后重判（事件循环现有 spec_ready 重触发通道）
3. 无 → 既有派发路径

判定口径：reviewer run 通过 agent_runner 的活动 run 表（非终态）精确判定，避免 status 快照竞态。

## D3: 合并收尾 ready 态兜底（合并推进处）

实现 run 合并完成后推进 implemented 的位置（engine 合并收尾回调）：

```python
current = state_machine.read_one(spec_name)
if current.get("status") == "ready" and _is_implementer_merge(spec_name, branch):
    # 竞态回退兜底：先合法补记 implementing，再推进 implemented
    state_machine.transition(spec_name, implementing_from="ready", evidence="concurrency-flight-guard 兜底")
state_machine.transition(spec_name, "implemented")
```

_is_implementer_merge：合并分支名匹配该 spec 的 implementer_run 记录（fenix/<spec>-<ts> 分支）且 merge 由实现流程驱动（非手工文档合并）。校验通过才兜底；否则维持原转移（ready→implemented 仍会被拒即反映异常）。

## D4: 测试策略

tests/test_spec_concurrency_guard.py：
- 回退守卫：mock spec_review 收口遇 implementing → 断言不回退、仅日志
- 派发校验：mock 在飞 reviewer → 断言派发顺延；review 收尾后重判派发
- ready 兜底：mock 合并收尾 ready+实现分支 → 断言自动补记 implementing 后 implemented、无 Invalid transition ERROR
- 幂等与不误报：非实现合并不触发兜底