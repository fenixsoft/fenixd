# Proposal: add-verdict-contract-singularity

## Why

裁决证据格式契约现手写在两处：`agents/planner-judge.md`（LLM 阅读的契约文本）与 `core/verdict_check.py`（框架确定性校验器）。两处靠人工保持一致：`VERDICT_CLASSES` 四分类取值、`NON_PASS_STATUSES` 非 PASS 状态集、evidence 三维度字段、`assertion_triage` 条目字段、`FORCE_FAILED_CLASSES` 映射规则，任一侧单方面修改（改 prompt 措辞时漏改常量，或重构校验器时漏改 prompt）都会造成「文本说 A、校验器判 B」的隐性契约漂移——LLM 按 prompt 产出却被校验器驳回，触发裁决重试空烧 token，且因缺乏机械锚点，漂移只能靠事故反推发现。现状无任何测试建立两处的机械一致性。

## What Changes

- 新增同源锚定测试：读取 `agents/planner-judge.md` 契约文本，断言其与 `core/verdict_check.py` 导出常量逐字一致（四分类取值、非 PASS 状态集、evidence 三维度键名、assertion_triage 条目字段、强制 failed 映射分类集）
- 任一侧改动而另一侧未同步时测试失败，把「契约漂移」从事故后反推变为提交时拦截
- 不改 prompt 文本、不改校验器逻辑，纯增量测试

## Capabilities

### 新增能力

- `verdict-contract-singularity`：planner-judge 契约文本与 verdict_check 校验器常量的同源锚定（单测机械锁定，双源漂移即红）

## Impact

- 代码：无（不修改任何生产代码）
- 测试：新建 `tests/test_verdict_contract_singularity.py`
- 风险：prompt 文本为中文叙述+JSON 示例，锚定策略须容忍格式变化（按「取值逐字出现」断言而非全文比对），避免无害文案微调误伤
