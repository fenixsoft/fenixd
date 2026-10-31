## Deliverables

```yaml
- path: DESIGN.md
  kind: new
- path: docs/design-md-audit-2026-11.md
  kind: new
- path: skills/fenix-prototype/SKILL.md
  kind: modify
- path: skills/fenix-new/SKILL.md
  kind: modify
```

## 1. M1 普查成文

- [ ] 1.1 普查设计裁决材料源：`core/dashboard/static/src/pages/command-center/shared.ts`
      常量表（含定稿日期注记）、活跃与归档 SPEC 的设计文档与反目标段
      （`spec/changes/*/` 与 `spec/archive/*/`）、`docs/superpowers/specs/*.md` 定稿、
      `.history/` 原型定稿；汇总「条目 + 出处」清单（工作底稿，可落临时文件不入交付）
- [ ] 1.2 成文仓库根 `DESIGN.md`：四段结构（通用条款/一般域/例外域-大屏域首个实例/
      待裁决段），红线段置头部，正式条款逐条标注出处，无出处条目集中待裁决段；
      验证 `python3 skills/fenix-prototype/scripts/stack_profile.py --project . --pretty`
      输出的 `design_doc` 摘录包含头部红线条目

## 2. M2 两处 skill 接线

- [ ] 2.1 `skills/fenix-prototype/SKILL.md` §3.3 画像主题注入处增补设计候选契约：
      DESIGN.md 摘录未覆盖的版式/组件形态遵循 frontend-design skill 两遍式产出候选
      （仅填宪法空白 + 反模板自批判），冲突时宪法赢并在生成说明中注明
- [ ] 2.2 `skills/fenix-new/SKILL.md` 起草契约段增补：UI 相关 SPEC 引用 `DESIGN.md`
      作为设计约束来源；涉偏离的 SPEC 按偏离声明格式（条目+理由+适用范围）写声明段

## 3. M3 首轮偏离审计与修正案提案

- [ ] 3.1 静态审计：以 DESIGN.md 为检查清单扫 `core/dashboard/static/src/`（硬编码
      色值脱离 token 白名单/字号脱阶/animation/transition 残留/null 口径/
      tabular-nums），产出「页面 × 违规条目 × 代码证据（file:line）」清单
- [ ] 3.2 渲染对照：playwright-cli 命名会话（`-s design-audit`，不用 default 会话）
      截 overview/projects/settings/help/command-center 五屏，与宪法视觉对照；
      dashboard 不可达时降级为静态扫结论 + 在审计文档显式标注渲染对照遗留，不得静默跳过
- [ ] 3.3 汇总 `docs/design-md-audit-2026-11.md`：三分类清单（(a) 无声明偏离→改代码
      清单（只列不改）/ (b) 已声明偏离→例外域覆盖核对 / (c) 宪法错漏）+ 待裁决段
      逐条呈报 + (b)(c) 类的 diff 级修正案提案（含出处表）；写入动作留待用户确认后
      按修正案程序执行（人工步骤，不进本任务清单）
