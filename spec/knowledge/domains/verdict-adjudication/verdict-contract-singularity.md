<!-- knowledge: capability=verdict-contract-singularity rev=1 sources=spec/archive/2026-09-15-add-verdict-contract-singularity -->

# 裁决契约单一性

planner-judge 契约文本与 verdict_check 校验器常量的同源锚定：契约漂移在提交时被测试拦截，而非事故后反推。

## 现行规则

- 同源锚定测试断言 `core/verdict_check.py` 契约常量与 `agents/planner-judge.md` 契约文本机械一致：`VERDICT_CLASSES` 每个取值在 prompt 中作为合法分类出现；`FORCE_FAILED_CLASSES` 每个取值与「MUST 映射为 failed」的映射表述共现。
- `NON_PASS_STATUSES` 每个状态值（fail/failed/error/warning）在 planner-judge.md 需增强场景的描述中出现。
- evidence 三维度键名（failed_assertions / screenshots / first_failed_step）与 assertion_triage 条目字段（assertion / classification / evidence）在 planner-judge.md 的结构定义中出现。
- 哨兵防未注册取值：planner-judge.md 中作为「合法分类」推荐的取值集合不得超出 `VERDICT_CLASSES`（防 prompt 私增分类值后被校验器必然驳回的漂移形态）。
- 任一侧改动而另一侧未同步时锚定测试失败，失败消息指明缺失的分类名/字段与对应常量或判定函数。
- 锚定断言基于「取值逐字出现」，不依赖段落结构、换行或措辞；prompt 文案的格式微调不致测试红。

## 溯源

- 2026-09-15 add-verdict-contract-singularity（spec/archive/2026-09-15-add-verdict-contract-singularity） — 新增契约文本与校验器常量的同源锚定测试（四分类取值、非 PASS 状态集、evidence 键名、triage 字段、强制 failed 映射集与哨兵防私增）
