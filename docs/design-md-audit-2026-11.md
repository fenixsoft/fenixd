# DESIGN.md 首轮偏离审计（2026-11）

> 依据：仓库根 `DESIGN.md`（界面设计宪法，add-design-md-governance 1.2 成文）。
> 方法：静态代码扫（`core/dashboard/static/src/`，检查清单 = 硬编码色值脱离 token
> 白名单 / 字号脱阶 / animation·transition 残留 / null 口径 / tabular-nums）+ 渲染
> 对照（playwright-cli 命名会话 `design-audit`，未占用 default 会话）。
> 纪律：本审计只列不改——(a) 类修复另立变更；修正案写入待用户确认后按 DESIGN.md
> 修正案三步程序执行。
> 证据存档：`.fenix/verify-evidence/add-design-md-governance/`（scan-colors-anim.txt /
> scan-type-null.txt / cc-snapshot.yml / overview-snapshot.yml / design-audit-shots/
> 五屏截图）。

## 0. 审计方法与覆盖

- 静态扫对象：`core/dashboard/static/src/` 全量（pages / components / global.less），
  原始扫描转储见证据存档两个 scan-*.txt。
- 渲染对照：五屏截图（overview / projects / settings / help / command-center，
  hash 路由逐一捕获，md5 各异）；command-center DOM 快照实测「—」占位 ×20，
  组织总览 / 执行台账 / 流水线 / 收件箱区块在位，运行中 / 空闲徽标在位。
- **渲染对照降级标注（显式遗留，未静默跳过）**：五屏截图与 DOM 结构对照已完成；
  **像素级颜色对照**因本实现环境禁读图件而降级——颜色级视觉终验（一般域浅色基线、
  大屏域深蓝黑四色的实屏观感）留待人工查看截图（证据存档路径）或后续轮补验。

## 1. 三分类清单

### (a) 无声明偏离 → 改代码清单（只列不改，修复另立）

| # | 违规条目（宪法出处） | 页面/组件 × 代码证据（file:line） | 说明 |
|---|---|---|---|
| a-1 | 静态渲染红线（DESIGN.md 红线§1） | `components/claude-composer/`：SessionComposer.tsx:349、CommandMenu.tsx:391、ComposerMenuPrimitives.tsx:87、PromptInput.tsx:54,150,190；`components/claude-msg/`：Markdown.tsx:135、MessageItem.tsx:68、ToolGroupContainer.tsx:68,73、Reasoning.tsx:86,91、ToolCard.tsx:38 —— tailwind `transition-*` 类 | 两族组件迁移自 claudecodeui（第三方视觉语言）；起草 SPEC（2026-10-03-add-session-composer 等）无偏离声明段，按「未声明偏离即真违规」判据入清单。**联动**：(c) 修正案提案 C1 / 待裁决 #5 裁决豁免与否；裁决不豁免则剔除 `transition-*` 类改静态切换 |
| a-2 | 配色单源红线（红线§3，域 token 单源存放） | `pages/projects/topology/index.tsx:36-37`、`PipelineView.tsx:299,469,517,521,529,589`、`SwimlaneView.tsx:80` —— 大屏域四源同族色（#d6e7f7 / #7f9cba）以字面量散落 | 色值本身合宪（大屏域 token 同族），违单源存放：command-center/shared.ts 是常量单源而 topology 各文件自带副本。改法（另立）：抽共享常量模块（先例：utils/runVisual.ts、collab-graph design.md D6） |
| a-3 | 配色单源红线（红线§3，一般域 antd token 基线） | `#1677ff`（antd 默认 primary 字面量 ×14）：projects/list.tsx:96,277,374,488、projects/detail.tsx、projects/progressPhase.ts:8,62、overview/components/IntroduceRow.tsx:129,299、ProjectCards.tsx:413、components/StatusTag.tsx:7、markdown-shared.tsx:105；`#108ee9`（旧 v3 蓝，脱现行色板）：IntroduceRow.tsx:105、ProgressBarTile.tsx:44、RegressionTab.tsx:275 | 与 antd 默认值同值的字面量在主题 token 变更时脱钩；`#108ee9` 已非现行色板。改法（另立）：改引 `theme.useToken()` token 或 antd 语义色 |
| a-4 | 灰字走 colorTextTertiary（通用条款§数据墨水） | global.less:35、activities/index.tsx:141、activities/components/AdminRunModal.tsx:43、projects/components/AdminInvokeModal.tsx:324 —— 手写灰 `#8c8c8c`；projects/detail.tsx:1687、projects/qualityGates.ts:54 —— `#999` | 手写灰阶字面量脱离 antd 文字 token。改法（另立）：`token.colorTextTertiary` / `colorTextQuaternary` |
| a-5 | 字号与数字排版红线（红线§4，tabular-nums） | 全域现状仅 OrgGrid.tsx:180（大屏域）与 claude-msg/ToolCard.tsx:55 使用；一般域数值列（projects/list.tsx 成本/时长列、detail.tsx 指标、activities/index.tsx 数值列）均无 `fontVariantNumeric` | **联动待裁决 #3**（适用范围：全域强制 or 仅大屏域）：裁决全域强制则本条为改代码清单；裁决收窄则本条撤销并走修正案 C3 收窄红线措辞 |

字号脱阶说明：`fontSize 11/13/15/17`（13 ×21、11 ×9、15 ×2、17 ×2，分布见
scan-type-null.txt）——因字号阶具体值在待裁决段 #1（阶值未经用户裁决），本轮**不判
违规**，仅作为现状普查证据支撑待裁决 #1。

null 口径核对：静态扫未发现「缺口显 0」渲染违规（detail.tsx:67 `num` 系判定逻辑非
渲染占位；detail.tsx:1799-1802 有 null 守卫）；command-center DOM 实测「—」×20。
合规。唯「时长未知 / 未知原因」类文本占位引出 (c) C2 措辞澄清。

### (b) 已声明偏离 → 例外域覆盖核对

| 偏离 | 声明出处 | 核对结论 |
|---|---|---|
| 大屏域深蓝黑四色单源替代 antd 浅色 token | add-command-center design.md（D6 + 风险节「复用既有 antd 暗色 token…不引入新色板」）+ shared.ts:7-11 注记 | DESIGN.md 例外域「大屏域」已覆盖 ✓（含用途声明 / 域专属 token / 偏离清单三件套） |
| collab-graph / spec-topology 大屏并入同色系 | collab-graph-bigscreen design.md D6/D7（「与协作图谱/拓扑大屏同一色系」shared.ts 注记） | 例外域已并入 ✓；唯单源**存放**未见 SPEC 声明 → 字面量副本列 (a) a-2，非 (b) 项 |
| claude-msg / claude-composer 族 tailwind 视觉语言 | 无偏离声明段 | 不属 (b)——列 (a) a-1 + (c) C1 |

(b) 类无需修正案补录：例外域条款覆盖完整。

### (c) 宪法错漏 → diff 级修正案提案（等用户确认，确认前不改 DESIGN.md）

**C1 新增「迁移件豁免」条款（联动待裁决 #5）**

```diff
## 红线（全域生效，违反即审计真违规）
…
+### 迁移件豁免（待裁决后生效）
+- 经用户裁决豁免的第三方迁移组件族（现候选：claude-msg / claude-composer，迁移自
+  claudecodeui）保留其原视觉语言（tailwind transition-* 等），不适用静态渲染红线；
+  豁免族清单在本节登记，新迁移件入族须走本修正案程序。（出处：首轮审计 2026-11
+  a-1 发现 + 用户裁决）
```

- 出处表：claude-composer/SessionComposer.tsx:2-4（「迁移自 claudecodeui」注记）、
  claude-msg/ToolCard.tsx:1-2（同）；2026-10-03-add-session-composer（归档，定稿
  评审含该视觉形态，无偏离声明段）；DESIGN.md 红线§1。
- 影响：豁免 → a-1 撤销；不豁免 → C1 改为登记「豁免否决」仅存档。

**C2 null 口径红线措辞澄清**

```diff
-- null 口径红线：数据缺口（null / undefined / 口径不可得）一律显示「—」，颜色与
-  数字都不得伪装缺口——MUST NOT 显示 0（0 与「口径不可得」语义不同）。（出处：…）
+- null 口径红线：数值 / 指标类数据缺口（null / undefined / 口径不可得）一律显示
+  「—」，颜色与数字都不得伪装缺口——MUST NOT 显示 0（0 与「口径不可得」语义不同）；
+  文本型未知值（如降级说明里的 run / 时长）可用中文限定词（「未知 run」「时长未知」），
+  不强制「—」。（出处：command-center-console-ui spec 原义为 KPI/台账数值列 +
+  首轮审计 2026-11 对 detail.tsx:1799-1802 文本占位的核对）
```

**C3 字号阶定稿入宪（联动待裁决 #1）**

```diff
 ## 通用条款（跨域共享）
-- 字号阶纪律：字号只准取自既定阶，MUST NOT 随手夹中间值；具体阶值见待裁决段 #1
-  （现状普查已呈报，裁决后经修正案入本条）。
+- 字号阶纪律：字号只准取自既定阶 11 / 12 / 13 / 14 / 16 / 18 / 28（副文本 11-12 /
+  正文 13-14 / 区块标题 16-18 / 大数值 28，以用户裁决为准），MUST NOT 随手夹
+  15 / 17 等中间值。（出处：待裁决 #1 经用户裁决后转正）
```

（阶值以用户裁决结果为准，上例仅为提案形态示例。）

## 2. 待裁决段逐条呈报（DESIGN.md 待裁决段 + 本轮新增，留用户逐条裁决）

| # | 条目 | 现状证据 | 裁决动作 |
|---|---|---|---|
| 1 | 字号阶具体取值 | fontSize 分布 11×9 / 12×90 / 13×29 / 14×31 / 16×7 / 18×4 / 20×1 / 24×1 / 28×5（scan-type-null.txt） | 定阶（提案：12/14/16-18/28 主力，11/13 收敛与否）→ 走修正案 C3 |
| 2 | 浅灰卡片 #f6f6f6/#efefef 适用范围 | 现状仅 settings 页（global.less:25-29） | 明示「仅 settings」或「一般域统一卡底」 |
| 3 | tabular-nums 适用范围 | 现状仅大屏域 OrgGrid + 迁移件 ToolCard | 全域强制（a-5 生效）或收窄大屏域（修正案收窄红线） |
| 4 | 一般域语义色沿用 antd 默认色板 | 现状 mostly antd 语义色，无明示裁决 | 明示沿用（推荐）或另定 |
| 5 | 迁移件豁免（本轮新增） | claude-msg / claude-composer 族 transition-* 残留（a-1） | 豁免入宪（修正案 C1）或否决（a-1 维持改代码清单） |

## 3. 渲染对照记录

- 会话纪律：playwright-cli `-s=design-audit` 命名会话全程使用，未占用 default 会话，
  截毕已 close。
- 五屏：overview / projects / settings / help / command-center（hash 路由，md5 互异，
  证据存档 design-audit-shots/）。
- DOM 对照：command-center 快照实测「—」占位 ×20、组织总览 / 执行台账 / 流水线 /
  收件箱区块在位（cc-snapshot.yml）；overview 结构正常（overview-snapshot.yml）。
- 遗留：像素级颜色对照降级（见 §0），不静默跳过。

## 4. 审计结论

- (a) 类 5 项（a-1 ~ a-5，其中 a-5 联动待裁决 #3）——只列不改，修复另立变更。
- (b) 类核对通过，例外域覆盖完整，无需补录。
- (c) 类 3 项修正案提案（C1 迁移件豁免 / C2 null 口径措辞 / C3 字号阶定稿）——
  **等用户确认后**按 DESIGN.md 修正案三步程序执行写入；确认前 DESIGN.md 不变。
- 待裁决 5 条呈报用户（§2）。
