## ADDED Requirements

### Requirement: 平台移植类 SPEC 首个采集里程碑含观测交付

起草平台移植/新采集链路类 SPEC 时，首个采集（取流/解码）里程碑的验收项 MUST 含可观测性交付：输入帧 dump、管线逐级计数、坏事件分类统计至少其二（允许按平台等价替代），与功能交付同批验收。

#### Scenario: 出题即带观测

- **WHEN** planner 为平台移植/新采集链路类需求起草 SPEC
- **THEN** 首个采集里程碑的任务与 Deliverables 含上述观测交付项，不待问题出现后补插桩

#### Scenario: 检查单与提示一致

- **WHEN** 起草方对照 skills/fenix-new/SKILL.md 检查单与 agents/planner-plan.md 提示
- **THEN** 两处对该约束的表述一致，无相互矛盾的条件