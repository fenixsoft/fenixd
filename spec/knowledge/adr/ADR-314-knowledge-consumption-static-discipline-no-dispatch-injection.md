# ADR-314：知识消费走静态纪律行，不做派发时动态注入

date: 2026-11-03
status: accepted

## Context

知识真相源 `spec/knowledge/`（851 个 md）运转近月消费为零：全部车道提示词无指路文字、`prompt_builder` 无知识注入，车道 agent 立项/实现/排查一律从零搜索代码库，蒸馏产物自产自销。备选方案是由 `prompt_builder` 在派发时按任务挑选知识页注入 prompt——但知识量大，「任务 → 页面」需要额外映射机制，且每次派发都产生强制 token 开销，开销随知识规模线性增长。

## Decision

消费契约由 `agents/*.md` 静态纪律行承担：六个消费车道（planner-plan、implementer、code-fix、administrator、self-review、arbiter）各含一段知识纪律，交互会话由项目 `CLAUDE.md` 与 fenix skill 指路承担。读 `spec/knowledge/index.md` 是硬纪律，下钻以「命中相关域」为条件（条件 MUST），下钻深浅由 agent 自判；不做派发时动态知识注入，也不引入项目级配置门控——纪律行带存在性条件，项目尚无 `spec/knowledge/` 目录时静默跳过，靠此在全部项目间自然分层。

## Consequences

零新代码路径、零派发强制 token 开销，知识规模增长不推高派发成本；纪律行随 `agents/` 框架级文件对全部项目生效。代价是下钻质量依赖 agent 自判与 index 简介质量——index 须保持精瘦且每域简介须能独立支撑「任务 ↔ 域」判断，纪律形式化（为合规全量阅读）的风险由「未命中可跳过、MUST NOT 全量阅读」文案对冲。后续知识相关 SPEC（回填管道等）同在此框架内，改走注入机制须显式 supersede 本裁定。
