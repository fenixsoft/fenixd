# Design: add-verdict-contract-singularity

## Context

裁决证据契约双源并存：`agents/planner-judge.md`（LLM 阅读的契约文本，中文叙述 + JSON 示例）与 `core/verdict_check.py`（框架确定性校验器，Python 常量）。需锚定的一致面：`VERDICT_CLASSES`（四分类取值）、`NON_PASS_STATUSES`（非 PASS 状态集）、evidence 三维度键名（failed_assertions / screenshots / first_failed_step）、`assertion_triage` 条目字段（assertion / classification / evidence）、`FORCE_FAILED_CLASSES`（强制 failed 映射集）。现状无机械一致性保证，单侧修改即隐性漂移。

## Goals / Non-Goals

- Goals：单测锚定两处一致面；漂移在提交时拦截而非事故后反推
- Non-Goals：不改 prompt 文本、不改校验器逻辑；不做模板渲染/JSON Schema 等重档同源化（探索中明确为后续选项）

## Decisions

### D1. 锚定策略：取值逐字出现断言，非全文比对

测试读 `agents/planner-judge.md` 源文本，对每个一致面断言「校验器常量的每个取值在文本中出现」：枚举值（product-bug 等四值、fail/failed/error/warning 四状态）、字段名（failed_assertions 等）、映射关系关键词（product-bug/test-defect 与 MUST failed 共现段）。不做全文/段落比对——prompt 是中文叙述文档，格式变化（换行、措辞微调）不应误伤；锚定目标是**取值集合**的一致性。

### D2. 常量从 verdict_check 导入，不复制

测试直接 `from core.verdict_check import VERDICT_CLASSES, ...`，锚定预期值零复制——常量改动即测试输入变化，与 prompt 文本比对天然成立。双向覆盖：常量改了文本没跟 → 对应取值在文本中找不到 → 红；文本改了常量没跟 → 同理红。

### D3. 反向漂移用例

除正向一致性外，加一组「哨兵」用例：断言 prompt 文本中**不存在**与常量冲突的取值（如四分类之外未被废弃的旧分类值仍在文档中被当作合法分类推荐）。哨兵从常量集取补集语义，防 prompt 新增未入常量的分类值。

## Risks / Trade-offs

- `[低]` prompt 文案重构可能触碰锚定断言（如字段名段落被改写）→ 测试失败即提醒同步，属预期行为；断言消息中给出对应常量名便于定位
- `[低]` prompt 文件路径依赖 repo 布局（agents/ 目录）→ 与 test_judge_efficiency.py 现行读法一致，无新增风险

## Migration Plan

纯新增测试文件，无迁移。

## Open Questions

- 无
