# Design: add-design-md-governance

## Context

用户与 AI 已完成完整 brainstorm，定稿设计文档在
`docs/superpowers/specs/2026-10-31-design-md-governance-design.md`（含生态调研、宪法
结构、修正案程序、审计方法、接线方案的全部论证）。本文档不重复论证，只记录落地实现
的关键决策。约束：只做文档层，不做门禁；零运行时代码改动；agent 无宪法直写权。

## Goals / Non-Goals

- Goals：DESIGN.md 成文（宪法）、首轮审计三分类清单、修正案 diff 级提案、
  fenix-prototype / fenix-new 两处 skill 起草契约接线。
- Non-Goals：门禁检查器、审计发现的代码修复（另立）、ui-ux-pro-max 引入、
  stack_profile.py 改动、组件库迁移。

## Decisions

1. **宪法落仓库根 `DESIGN.md`**（非 docs/ 下）：`stack_profile.py:261` 的候选路径
   首位是根路径；摘录逻辑按视觉关键词行筛选、封顶 40 行——红线段置文档头部确保稳定
   入选；正文紧凑（对应记忆：扫描器摘录上限）。
2. **例外域泛化结构**（用户定稿修正）：大屏域不是「特例硬编码」而是例外域的第一个
   实例；每域 = 用途声明 + 域专属 token + 偏离清单；未来移动应用等新域按同一模板
   扩小节。
3. **出处纪律 = 宪法合法性判据**：正式条款必须能在材料源中指认（SPEC 名/定稿日期/
   shared.ts 注记）；无出处条目一律进待裁决段。宪法记录现状，不立新宪。
4. **审计产物落 `docs/design-md-audit-2026-11.md`**（审计三分类清单 + 待裁决段呈报 +
   修正案 diff 级提案合一文档）：不落 spec/changes 目录内（该目录由脚手架/daemon
   管理，混入实现产物会干扰 artifact 对账）。
5. **修正案写入不进任务门禁**（任务粒度纪律 §3.2.1：「用户确认后写入」是人工裁决，
   Agent 单次 run 内无法与人往返）：tasks 只到「产出 diff 级提案文档」为止；确认与
   写入是 DESIGN.md 自身修正案程序的人工步骤，验收时用户当场确认后由 AI 会话内执行
   或留待下轮。
6. **渲染对照用 playwright-cli 命名会话**（记忆：default 会话与在飞 run 共享）：
   截五屏（overview/projects/settings/help/command-center）与宪法对照；dashboard 为
   只读 GET 面，截图无破坏性 POST 风险。
7. **frontend-design 替代 ui-ux-pro-max**（用户定稿）：两遍式流程原生产出候选 token
   系统 + 反 AI 俗套自批判；接入点写进 fenix-prototype 生成契约（§3.3 画像主题注入
   邻位），宪法摘录约束优先。
8. **fenix-new 接线加在起草契约段**：UI SPEC 引用 DESIGN.md + 涉偏离写声明段；
   `add-timeline-origin-request` 等 fenix-new 既有行为 SPEC 不受影响（本变更是新增
   约定，非改既有 Requirement）。

## Risks / Trade-offs

- 摘录 40 行上限可能截断宪法正文 → 红线前置 + 正文紧凑（宪法是约束摘要不是散文）。
- 首轮审计的「无出处」判定可能有误伤（出处材料源覆盖不全）→ 待裁决段机制兜底，
  误伤条目经用户裁决后走修正案转正。
- 审计渲染对照依赖 dashboard 本地可访问 → 不可达时静态扫先行、渲染对照降级为遗留项
  在审计文档中显式标注，MUST NOT 静默跳过。

## Migration Plan

纯新增文档 + 两处 skill 增补，无数据迁移、无行为回退面。回滚 = 删 DESIGN.md 与审计
文档、还原两处 SKILL.md 段落。

## Open Questions

无（brainstorm 已全部定稿：执行模式 full、立即执行、修正案三步、例外域泛化）。
