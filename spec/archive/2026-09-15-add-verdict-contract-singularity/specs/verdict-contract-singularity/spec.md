# verdict-contract-singularity — planner-judge 契约文本与 verdict_check 常量同源锚定

## ADDED Requirements

### Requirement: 分类枚举同源
测试 SHALL 断言 `core/verdict_check.py` 的 `VERDICT_CLASSES` 每个取值在 `agents/planner-judge.md` 中作为合法分类出现；`FORCE_FAILED_CLASSES` 的每个取值 SHALL 与「MUST 映射为 failed」的映射表述共现。

#### Scenario: 常量改动文本未跟时测试红
- **WHEN** verdict_check.py 新增/更名一个分类取值而 planner-judge.md 未同步
- **THEN** 锚定测试失败，失败消息指明缺失的分类名与对应常量

#### Scenario: 文本改动常量未跟时测试红
- **WHEN** planner-judge.md 重写分类定义段而 verdict_check.py 常量未同步
- **THEN** 锚定测试失败

### Requirement: 非 PASS 状态集同源
测试 SHALL 断言 `NON_PASS_STATUSES` 每个状态值（fail/failed/error/warning）在 planner-judge.md 需增强场景的描述中出现。

#### Scenario: 状态集漂移拦截
- **WHEN** 校验器调整非 PASS 状态集而 prompt 步骤段未同步
- **THEN** 锚定测试失败

### Requirement: 证据结构字段同源
测试 SHALL 断言 evidence 三维度键名（failed_assertions / screenshots / first_failed_step）与 assertion_triage 条目字段（assertion / classification / evidence）在 planner-judge.md 的结构定义中出现。

#### Scenario: 字段名漂移拦截
- **WHEN** 校验器 evidence 判定逻辑改用新键名而 prompt 示例未同步
- **THEN** 锚定测试失败，消息指向 verdict_check 中对应判定函数

### Requirement: 哨兵防未注册取值
测试 SHALL 断言 planner-judge.md 中作为「合法分类」推荐的取值集合不超出 `VERDICT_CLASSES`（防 prompt 新增分类值未入常量集，校验器必然驳回的漂移形态）。

#### Scenario: prompt 私增分类值拦截
- **WHEN** planner-judge.md 分类定义段出现 VERDICT_CLASSES 之外的候选取值
- **THEN** 锚定测试失败

### Requirement: 锚定 tolerate 无害文案变化
锚定断言 SHALL 基于「取值逐字出现」，MUST NOT 依赖段落结构、换行或措辞（prompt 文案的格式微调不应致测试红）。

#### Scenario: 文案微调不误伤
- **WHEN** planner-judge.md 措辞/排版调整但全部锚定取值保留
- **THEN** 锚定测试通过
