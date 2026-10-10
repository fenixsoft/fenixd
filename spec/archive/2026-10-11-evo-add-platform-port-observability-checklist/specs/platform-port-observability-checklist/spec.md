## ADDED Requirements

### Requirement: 平台移植类 SPEC 首个采集里程碑含观测交付

起草平台移植/新采集链路类 SPEC 时，首个采集（取流/解码）里程碑的验收项 MUST 含可观测性交付：输入帧 dump、管线逐级计数、坏事件分类统计至少其二（允许按平台等价替代），与功能交付同批验收。

#### Scenario: 起草即带观测

- **WHEN** 起草方（fenix-new 立项流程）为平台移植/新采集链路类需求起草 SPEC
- **THEN** 首个采集里程碑的任务与 Deliverables 含上述观测交付项，不待问题出现后补插桩

#### Scenario: 检查单与评审门禁一致

- **WHEN** 起草方对照 skills/fenix-new/SKILL.md 检查单与 agents/spec-review.md 评审检查单，或 spec-review 评审平台移植/新采集链路类 SPEC
- **THEN** 两处对该约束的表述一致，无相互矛盾的条件；首个采集里程碑缺观测交付项的 SPEC 在评审门禁被打回或就地补齐