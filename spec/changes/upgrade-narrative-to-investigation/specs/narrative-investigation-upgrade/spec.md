# narrative-investigation-upgrade 规格

## ADDED Requirements

### Requirement: 按 signal_type 的证据采集

叙事生成前 MUST 采集结构化验证材料注入 prompt，采集器按 signal_type 注册：

- 验证族信号（judge_rerun_cap / inconclusive_loop / verdict 相关预算与闸门族）通用采集：
  - `spec/changes/<spec>/verification-report.md` 全文（截断至段落预算）；
  - `.fenix/verify-progress/<spec>/report.json` 的 summary 与失败/警告场景表（含 classification 分布）；
  - `.fenix/verify-progress/<spec>/verdict_stability.json` 的 rounds 历史（判定轮次与状态序列）；
  - `.fenix/verify-progress/<spec>/fail_history.json` 的轮次演进；
- 采集全部 fail-open：任一文件缺失/损坏跳过该段，不阻断叙事生成；
- 总上下文预算 16K 字符，分段截断（段界保留、截断标记标注）。

#### Scenario: 验证族告警叙事包含调查材料

- **WHEN** judge_rerun_cap 告警触发叙事生成且上述四个产物文件齐备
- **THEN** prompt 含报告正文摘要、失败场景 classification 分布、判定轮次历史与轮次演进段

#### Scenario: 材料缺失降级不阻断

- **WHEN** 非 verify 族信号（如 spec-review-rejected）或产物文件缺失
- **THEN** 对应段跳过，叙事按既有机械字段 + STATE 条目正常生成（与升级前行为兼容）

### Requirement: 四段叙事结构

叙事输出结构从三段升级为四段，标题逐字固定且顺序不可变：

1. `## 发生了什么`
2. `## 调查结论`
3. `## 为什么需要你决策`
4. `## 决策选项`

prompt 指令要求：调查结论段基于【验证材料】给出根因判断并引用具体证据（计数器/预算/环境事实）；材料不足以定位时 MUST 明确写「材料不足以定位」并给出建议查证路径；材料内有据可依的因果推断必须给出，材料外事实不得编造。

机械校验（`_validate_structure`）同步升级为四段齐全且顺序不倒置；既有三段输出校验为失败（走兜底）。

#### Scenario: 四段结构校验

- **WHEN** 模型输出含四段固定标题且顺序正确
- **THEN** 校验通过，narrative 正常落盘渲染为四段

#### Scenario: 缺段输出走兜底

- **WHEN** 模型输出缺「调查结论」段（仍按旧三段输出）
- **THEN** 结构校验失败，告警以机械文案落盘（无 narrative 字段），WARNING 留痕

### Requirement: 异步补叙（告警零阻塞落盘）

叙事生成从同步改异步：

- 告警发射点 MUST 以机械文案**立即落盘**（叙事调用不落盘路径零阻塞、零延迟）；
- 落盘后后台生成叙事；完成经**原子补写**到独立侧车 `.fenix/admin_alerts_narrative/<alert_id>.json`（结构 `{"alert_id", "text", "model", "at"}`，mkstemp + os.replace 原子写）——admin_alerts.json 记录本体不可变，侧车承载补叙；
- 告警读侧（Dashboard 数据层）按 alert_id 合并侧车 narrative 字段渲染；
- 超时 180s（`admin.narrative_timeout_seconds` 缺省同步改 180）、至多 2 次尝试（2 次全败写 WARNING 后放弃，不重试风暴）；
- 人工已处置（handled）后补叙照常落盘（历史完整性优先），处置流程不受影响；
- 2 次尝试全败、或熔断生效期跳过生成时，MUST 写终态侧车（同目录同结构，`text` 为机械说明、`model` 为 null）——失败/跳过告警 MUST NOT 以 `narrative_pending` 悬挂「调查生成中」假态。

#### Scenario: 告警先落盘后补叙

- **WHEN** 转人工告警发射且叙事通道开启
- **THEN** 告警记录在叙事调用发起前已可读（落盘耗时不含 LLM 时延）；数十秒后侧车文件出现且前端渲染出 narrative

#### Scenario: 补叙失败告警完整可用

- **WHEN** 叙事 2 次尝试均超时
- **THEN** 告警本体始终以机械文案完整可用（choices/处置闭环不受影响），补叙侧车不出现、代之以终态失败说明侧车（前端渲染失败说明而非「调查生成中」），WARNING 留痕

### Requirement: 连续失败熔断

叙事生成失败（超时/空输出/结构校验失败）按滑动窗口计数：

- 连续 3 次失败 → 熔断生效，冷却窗口（1 小时）内新告警跳过叙事生成（零调用零延迟）；
- 冷却期内零调用，不存在「期间成功」复位路径；冷却到期后恢复尝试，恢复后一次成功即清零计数；熔断跳过的告警按「异步补叙」Requirement 写终态侧车；
- 熔断生效与解除均 WARNING 留痕；`admin.narrative_enabled=false` 时熔断器旁路（整体关闭优先）。

#### Scenario: 网关事故期熔断止血

- **WHEN** 网关长尾导致连续 3 条告警叙事超时
- **THEN** 第 4 条起跳过生成（无 LLM 调用）并写终态「叙事熔断中」侧车（不悬挂生成中假态），冷却 1 小时后自动恢复尝试
