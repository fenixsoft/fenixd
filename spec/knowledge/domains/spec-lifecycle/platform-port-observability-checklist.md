# 平台移植观测交付检查单
<!-- knowledge: capability=platform-port-observability-checklist rev=1
     sources=spec/archive/2026-10-11-evo-add-platform-port-observability-checklist -->

平台移植与新采集链路类 SPEC 在起草与评审两个环节的观测交付强制约束：可观测性插桩随首个采集里程碑同批交付，而非问题驱动滞后补齐。

## 规则

- 起草平台移植/新采集链路类 SPEC 时，首个采集（取流/解码）里程碑的验收项必须含可观测性交付：输入帧 dump、管线逐级计数、坏事件分类统计三类至少其二，与功能交付同批验收，任务与 Deliverables 均须体现，不待问题出现后补插桩。
- 观测项允许按平台等价替代（如无独立解码器时以采集回调 dump 等价物）；覆盖范围以「平台移植/新采集链路」措辞界定，不区分具体平台（Android/iOS/嵌入式），避免检查单过拟合单一栈。
- 约束有两处生效点，措辞一致、无相互矛盾的条件：
  1. skills/fenix-new/SKILL.md §3.2 交付段强制条目串末尾的强制条目（与 §3.2.1 任务粒度条款同族、同强制级）——第一道防线，起草（fenix-new 立项流程）时即带观测交付。
  2. agents/spec-review.md 评审维度检查区的同款条目——第二道防线，在起草后、实现前把关，不依赖起草方自觉。
- 评审发现首个采集里程碑缺观测交付项时，按既有 severity 判定标准处置：能在 SPEC 文档内补条款的判 repairable 就地修补；机制性缺失判 blocking 打回。

## 关键行为

- 该约束为约定强制（检查单级），无机械 lint：core/deliverables.py 不做机械判定，因项目类型（平台移植/采集链路）尚无 taxonomy，机械化留待分类机制建立后另立条目。
- 约束不落 schemas/spec-driven/templates/ 裸模板与 core/spec_gen.py：生成路径不感知该约束，生效完全依赖起草检查单与评审门禁两处。
- agents/planner-plan.md 与 spec/knowledge/ 蒸馏条目均不是本约束的生效点：前者是验证链测试场景出题提示（SPEC 定稿后运行、无 SPEC 起草权），后者只进 dashboard、不注入规划提示。

## 溯源

- 2026-10-11 evo-add-platform-port-observability-checklist（spec/archive/2026-10-11-evo-add-platform-port-observability-checklist） — 新建本页：平台移植/新采集链路类 SPEC 首个采集里程碑观测交付强制项（三类至少其二、允许等价替代），固化于 fenix-new 起草检查单与 spec-review 评审维度两处
