## Why

fenixd 的 UI 由 implementer agent 按 SPEC 逐轮产出，agent 无跨轮记忆，设计决策散落在
各 SPEC 定稿、`command-center/shared.ts` 常量表、事故记忆沉淀中——契约靠口口相传，
蒸馏治理已实证会漂移（每轮新 agent 重新犯同一类错）。DESIGN.md 是 Google Stitch 提出
的设计宪法约定（`AGENTS.md : 怎么建项目 :: DESIGN.md : 该长什么样`），且
fenix-prototype 的 `stack_profile.py:261` 已预留消费口（提取摘录注入原型生成
prompt）——落地文档层治理即可让每轮 UI 工作自动继承既定设计语言。用户定调：只做
文档层，不做门禁（机制层留待未来另立）。

## What Changes

- 新增仓库根 `DESIGN.md`（界面设计宪法）：四段结构 = 通用条款（字号阶/tabular-nums/
  null→「—」口径/静态渲染红线/antd 陷阱反模式族）+ 一般域（浅色五页）+ 例外域（大屏
  域为首个实例，结构可扩展后续新域）+ 待裁决段（无出处条目留用户裁决）；每条标注出处，
  红线置头部（stack_profile 摘录封顶 40 行，头部红线必须稳定入选）。
- 新增修正案程序（三步）：用户定稿事件取得回写资格 → AI 提 diff 级回写提案 → 用户
  确认后 AI 写入；agent 任何时刻无直写权。
- 新增 SPEC 级偏离声明格式：用户明确同意偏离宪法的，SPEC 设计文档必须列明偏离条目 +
  理由 + 适用范围；审计以「未声明偏离」为真违规判据。
- 首轮偏离审计：静态代码扫（色值白名单/字号阶/animation 残留/口径）+ 渲染对照
  （playwright-cli 命名会话截五屏），产出三分类清单（实现走样改代码 / 已声明偏离核对
  例外域覆盖 / 文档错漏走修正案）+ 待裁决段呈报 + diff 级修正案提案（写入动作留待
  用户确认后的人工步骤，不进本 SPEC 任务门禁）。
- fenix-prototype 生成契约接线：生成阶段遵循 frontend-design skill 两遍式产出候选
  （仅填宪法空白处 + 反模板自批判），与 DESIGN.md 冲突时宪法赢。
- fenix-new 起草契约接线：UI 相关 SPEC 起草时引用 DESIGN.md、涉偏离时写偏离声明段。
- 明确不引入 ui-ux-pro-max（frontend-design 已论证可替代，见设计文档 §8）。

## Capabilities

### New Capabilities

- `design-md-governance`: DESIGN.md 宪法四段结构、普查成文方法（材料源清单 + 只收
  已裁决条目原则）、修正案三步程序、SPEC 级偏离声明格式、首轮偏离审计三分类、
  fenix-new 起草接线。

### Modified Capabilities

- `ui-prototype-generation`: 生成契约新增「设计候选注入与宪法优先」要求——生成阶段
  遵循 frontend-design 两遍式产出候选（仅填宪法空白），DESIGN.md 摘录约束主题与
  组件选型，冲突时宪法赢。（现有能力定义见活跃变更
  `spec/changes/fenix-prototype/specs/ui-prototype-generation/spec.md`）

## Impact

- 新文件：`DESIGN.md`（仓库根）、`docs/design-md-audit-2026-11.md`（首轮审计三分类
  清单 + 待裁决段呈报 + 修正案 diff 级提案，合一文档）。
- 修改：`skills/fenix-prototype/SKILL.md`（生成契约增补设计候选注入 + 宪法优先）、
  `skills/fenix-new/SKILL.md`（UI SPEC 起草契约增补 DESIGN.md 引用与偏离声明段）。
- 零运行时代码改动：不碰 `core/`、不改 `stack_profile.py`（消费口已存在）、不做门禁
  检查器、不做组件库迁移。
- 审计为只读动作：静态扫源码 + playwright-cli 命名会话截图（避开在飞 run 共享的
  default 会话），不改 dashboard 代码；审计发现的实现走样修复另立。
