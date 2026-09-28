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

- [x] 1.1 core/pm_engine/engine.py：_FORWARDER_REGISTRY 在 "_preclassify_orphan"（:265）后补 "_preclassify_drift": ("_dispatcher", "_preclassify_drift")，键值形态与现有条目逐字同款
- [x] 1.2 tests/test_pm_facade_forwarder_contract.py：回归——PMEngine 实例经门面调 _preclassify_drift 转发到 Dispatcher._preclassify_drift（VAdjudicationMixin 真身），五参签名一致

## 2. 门面契约硬门

- [x] 2.1 tests/test_pm_facade_forwarder_contract.py：AST 扫描 self._pm.<name> 字面调用点，**按目录分桶**：core/pm_engine/** 调用点断言每个 name 可经 PMEngine 解析（core/agent_runner/** 调用点归 2.3 的 AgentRunner 门）；解析域 = 注册表键 ∪ 门面显式定义（含类体 def/类属性赋值、混入类、以及方法体内 self.<名> 实例属性赋值；dunder 与注释除外），失败输出缺失名与调用文件:行号
- [x] 2.2 tests/test_pm_facade_forwarder_contract.py：反向断言 PMEngine 注册表每条目 (sub_attr, meth) 经惰性 property + getattr 可解析，无悬空条目；合法不入表名字（门面显式方法、verification/pipeline.py:356 静态式转发豁免清单）不误报
- [x] 2.3 tests/test_pm_facade_forwarder_contract.py：AgentRunner（core/agent_runner/runner.py:433）与 VerificationPipeline（core/pm_engine/verification/pipeline.py:263）同构注册表纳入同规则检查——AgentRunner 调用点取 core/agent_runner/** 的 self._pm._ 命中；反向断言按条目形态分支（PMEngine 二元组 / VerificationPipeline `名: 模块函数` 单值，(sub_attr, meth) 解包不可跨形态机械套用）；VerificationPipeline 侧现状零 self._pm._ 回引（core/pm_engine/verification/context.py:74 契约目标），正扫为空集即在测试内书面说明，不强行断言
