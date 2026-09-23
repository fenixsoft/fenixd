## Deliverables

```yaml
# ── 注册表补登记 ──────────────────────────────────────────
- path: core/pm_engine/engine.py
  kind: modify

# ── 门面契约硬门测试 ────────────────────────────────────────
- path: tests/test_pm_facade_forwarder_contract.py
  kind: new
```

## 1. 补注册与回归

- [ ] 1.1 core/pm_engine/engine.py：_FORWARDER_REGISTRY 在 "_preclassify_orphan"（:265）后补 "_preclassify_drift": ("_dispatcher", "_preclassify_drift")，键值形态与现有条目逐字同款
- [ ] 1.2 tests/test_pm_facade_forwarder_contract.py：回归——PMEngine 实例经门面调 _preclassify_drift 转发到 Dispatcher._preclassify_drift（VAdjudicationMixin 真身），五参签名一致

## 2. 门面契约硬门

- [ ] 2.1 tests/test_pm_facade_forwarder_contract.py：AST 扫描 core/ 下全部 self._pm.<name> 字面调用点，断言每个 name 可经 PMEngine 解析（注册表键 ∪ 门面显式定义，dunder 与注释除外），失败输出缺失名与调用文件:行号
- [ ] 2.2 tests/test_pm_facade_forwarder_contract.py：反向断言注册表每条目 (sub_attr, meth) 经惰性 property + getattr 可解析，无悬空条目；合法不入表名字（门面显式方法、pipeline.py 静态式转发豁免清单）不误报
- [ ] 2.3 tests/test_pm_facade_forwarder_contract.py：AgentRunner（core/agent_runner/runner.py）与 VerificationPipeline（core/pm_engine/pipeline.py）同构注册表纳入同规则检查，无法机械化验证的调用面在测试内书面说明
