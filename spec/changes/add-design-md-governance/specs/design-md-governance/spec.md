## ADDED Requirements

### Requirement: DESIGN.md 宪法四段结构

仓库根 MUST 存在 `DESIGN.md`（界面设计宪法），按四段结构组织：

1. **通用条款**（跨域共享）：字号阶、`tabular-nums`、null→「—」口径、静态渲染红线
   （禁 CSS animation/transition/SMIL）、组件惯例、antd 陷阱反模式族；
2. **一般域**（默认法）：overview / projects / settings / help / activities 的浅色
   antd token 基线；
3. **例外域**（特别法）：每域独立小节 = 用途声明 + 域专属 token + 与一般域的偏离
   清单；大屏域（command-center 四屏，深蓝黑四色单源）为首个实例；结构 MUST 可扩展
   新界面域（如未来移动应用），不为未出现的域预写内容；
4. **待裁决段**：普查中无出处的条目集中于此，留用户逐条裁决。

静态渲染红线等红线类条目 MUST 置于文档头部显眼位置（`stack_profile.py` 摘录按视觉
关键词行提取且封顶 40 行，头部红线 MUST 能稳定入选摘录注入原型生成 prompt）。

#### Scenario: 例外域结构可扩展

- **WHEN** 未来出现新界面域（如移动应用）需要偏离一般域
- **THEN** 在例外域段新增一个独立小节（用途声明 + 域专属 token + 偏离清单）即可，
  无需改动通用条款与一般域结构

#### Scenario: 红线入选 stack_profile 摘录

- **WHEN** 对本工程跑 `stack_profile.py` 提取 DESIGN.md 摘录
- **THEN** 头部红线类条目（静态渲染红线、null 口径等）出现在摘录中，可注入原型生成

#### Scenario: 一般域与大屏域并存不冲突

- **WHEN** 同一工程内 overview（浅色）与 command-center（深蓝黑大屏）并存
- **THEN** 宪法将大屏域登记为例外域（含用途声明「大屏展示」），一般域默认法不受影响

### Requirement: 普查成文出处纪律

DESIGN.md 正式条款 MUST 只收「已发生过的用户裁决」，每条 MUST 标注出处（SPEC 名 /
定稿日期 / 常量表注记）；普查材料源 MUST 覆盖：`command-center/shared.ts` 常量表、
活跃与归档 SPEC 的已定稿设计文档与反目标段、`.history/` 原型定稿。无出处条目 MUST
进入待裁决段，MUST NOT 直接写入正式条款。

#### Scenario: 有出处条目入正式条款

- **WHEN** 普查发现某设计条目在某已定稿 SPEC 或用户定稿事件中有明确记载
- **THEN** 该条目写入对应域的正式条款并标注出处

#### Scenario: 无出处条目入待裁决段

- **WHEN** 普查发现某设计条目无法追溯出处（如实现中顺手引入的色值惯例）
- **THEN** 该条目进入待裁决段等待用户裁决，不写入正式条款

### Requirement: 修正案三步程序

DESIGN.md 的任何写入 MUST 遵循三步程序：① 用户定稿事件（原型批准 / SPEC 定稿 /
明示裁决）取得回写资格；② AI 提出 diff 级回写提案（新增/修改哪条、放哪个域、出处
标注）；③ 用户确认后 AI 执行写入。用户定稿事件本身 MUST NOT 自动触发写入；agent 在
任何时刻 MUST NOT 直写 DESIGN.md 正式条款。

#### Scenario: 定稿事件不自动写入

- **WHEN** 某原型获用户批准（定稿事件发生）
- **THEN** AI 仅取得回写资格，MUST 先提出 diff 级提案，用户确认前 DESIGN.md 不变

#### Scenario: 确认后写入

- **WHEN** 用户对某 diff 级回写提案明确确认
- **THEN** AI 按提案内容写入 DESIGN.md 并保留出处标注

### Requirement: SPEC 级偏离声明

用户明确同意偏离宪法的，该 SPEC 设计文档 MUST 包含偏离声明段：偏离条目 + 理由 +
适用范围（哪域/哪屏/哪组件）。偏离审计以「未声明偏离」为真违规判据；已声明偏离
MUST 核对 DESIGN.md 例外域条款是否同步覆盖，缺失的走修正案补录。

#### Scenario: 已声明偏离合法

- **WHEN** 某 SPEC 设计文档含偏离声明段（如「本屏允许 CSS 动画，理由 X，范围 Y」）
- **THEN** 实现按声明偏离不受宪法拦截，审计核对例外域条款覆盖情况

#### Scenario: 未声明偏离判违规

- **WHEN** 审计发现某实现与宪法冲突且其 SPEC 无偏离声明
- **THEN** 该偏离判为真违规（实现走样），进改代码清单

### Requirement: 首轮偏离审计三分类

宪法成文后 MUST 执行首轮偏离审计，方法 = 静态代码扫（硬编码色值脱离 token 白名单/
字号脱阶/animation 残留/null 口径/tabular-nums）+ 渲染对照（playwright-cli 命名
会话截图对照，避开在飞 run 共享的 default 会话）。发现 MUST 按三分类归档：
(a) 无声明偏离 → 实现走样，列改代码清单（修复另立，不在本变更内改）；
(b) SPEC 已声明的偏离 → 核对例外域条款覆盖，缺的走修正案补录；
(c) 宪法本身错漏 → 走修正案。审计产物 MUST 含待裁决段呈报与 diff 级修正案提案
（写入动作留待用户确认后的人工步骤）。

#### Scenario: 实现走样进改代码清单

- **WHEN** 静态扫发现某页存在宪法外硬编码色值且无偏离声明
- **THEN** 该发现归入 (a) 类改代码清单，本变更不直接修改该页代码

#### Scenario: 渲染对照用命名会话

- **WHEN** 执行渲染对照截图
- **THEN** 使用 playwright-cli 命名会话（不占用 default 会话），不干扰在飞 run

#### Scenario: 修正案提案不自动写入

- **WHEN** 审计产出 (b)/(c) 类修正案素材
- **THEN** 以 diff 级提案形式呈报，等待用户确认后另行写入

### Requirement: fenix-new 起草接线

`skills/fenix-new/SKILL.md` 的起草契约 MUST 增补：UI 相关 SPEC 起草时 MUST 引用
`DESIGN.md` 作为设计约束来源；涉及偏离宪法的 SPEC MUST 按偏离声明格式写入设计文档。

#### Scenario: UI SPEC 引用宪法

- **WHEN** fenix-new 为一个界面改动起草 SPEC
- **THEN** SPEC 设计文档引用 DESIGN.md，实现与评审可据此对照宪法

#### Scenario: 涉偏离 SPEC 带声明段

- **WHEN** 起草的 UI SPEC 习俗偏离宪法（用户已明确同意）
- **THEN** 设计文档包含偏离声明段（条目+理由+范围）
