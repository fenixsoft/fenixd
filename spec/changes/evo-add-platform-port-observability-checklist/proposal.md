## 背景

potplayer-base 的 Android 平台接入期间，帧级可观测性（解码器输入帧 dump、管线逐级计数）是问题驱动、滞后补齐的：SPEC android-station-port 的 tasks.md 22 条 Deliverables 无任何观测/插桩交付项；真机数据链路排障先以会话级统计过渡（eb00325），帧级 dump 与全量计数 832e20a（+80 行）才补齐，符号级统计（966edd1）与坏事件分类（f6f194c）更落在根因修复（78ba335）之后。插桩实测成本极小（+80 行）而缺观测的排障以小时计，且三件套最终全部存活为主树常态代码——说明接入时带上它们是低代价高回报的。

框架侧固化点调查结论：spec/knowledge/ 蒸馏条目只进 dashboard、不注入规划提示，不能作约束生效点；SPEC 起草的强制检查单先例在 skills/fenix-new/SKILL.md §3.2.1，规划车道提示真相源在 agents/planner-plan.md。本 SPEC 把「平台移植/新采集链路类 SPEC 首个采集里程碑必须含观测交付项」固化进这两处，零机制新增。

## 目标

- fenix-new 起草检查单增加平台移植类观测交付强制项（与 §3.2.1 任务粒度条款同族）。
- planner 出题提示同步该约束，使出题即带观测、不依赖起草方自觉。

## 非目标

- 不在 core/deliverables.py 增加机械 lint：项目类型（平台移植/采集链路）现无 taxonomy，机械判定留待分类机制建立后另立条目。
- 不改 schemas/spec-driven/templates/ 裸模板与 core/spec_gen.py。