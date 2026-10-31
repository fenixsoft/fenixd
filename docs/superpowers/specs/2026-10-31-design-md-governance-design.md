# DESIGN.md 治理体系（界面设计宪法）设计文档

日期：2026-10-31
状态：brainstorm 定稿（会话逐点确认），本文档为定稿记录，转 fenix-new 立项

## 1. 背景与意图

fenixd 的 UI 由 implementer agent 按 SPEC 逐轮产出，agent 无跨轮记忆，设计决策散落在
各 SPEC 定稿、`shared.ts` 常量表、事故记忆中——契约靠口口相传，已被蒸馏治理实证会漂移。
生态调研结论：DESIGN.md 是 Google Stitch 提出的约定（`AGENTS.md : 怎么建项目 ::
DESIGN.md : 该长什么样`），纯 markdown 放仓库根，任何 AI agent 可读（参考
VoltAgent/awesome-design-md 收录的 84 例成熟格式）。**fenix-prototype 的
`stack_profile.py:261` 已预留消费口**（候选路径 `DESIGN.md` / `docs/DESIGN.md` /
`doc/DESIGN.md`，提取含视觉关键词的行封顶 40 行注入原型生成 prompt）——建 DESIGN.md
不是加新机制，是激活既有钩子。

用户定调：**只做文档层治理，不做门禁**（门禁化留待未来另立）。

## 2. 目标 / 非目标 / 反目标

### 目标

1. 普查既有设计裁决，成文仓库根 `DESIGN.md`（宪法）。
2. 定义修正案程序：用户定稿 → AI 提案 → 用户确认 → 写入（三步）。
3. 定义 SPEC 级偏离声明格式。
4. 首轮偏离审计，产出三分类清单。
5. 新界面流程接线：fenix-prototype 双注入（DESIGN.md + frontend-design）。

### 非目标（本轮不做）

- 不做质量门禁 / design lint 检查器（文档层先行，机制层另立）。
- 不引入 ui-ux-pro-max（已论证可被 frontend-design 替代，见 §8）。
- 不改 `stack_profile.py`（消费口已存在）。
- 不做 antd 组件库迁移、不改既有页面代码（审计产物中的代码修正另立）。

### 反目标（出现即算失败）

- agent 获得任何 DESIGN.md 直写权。
- DESIGN.md 收录无出处、未经用户确认的新发明条目。
- 用户定稿事件自动触发回写（回写必须走提案—确认两步，缺一不可）。

## 3. DESIGN.md 宪法结构（域分层，定稿）

位置：仓库根 `DESIGN.md`（stack_profile 第一候选路径）。四段结构：

1. **通用条款**（跨域共享）：字号阶、`tabular-nums`、null→「—」口径、静态渲染红线
   （禁 CSS animation/transition/SMIL）、组件惯例、antd 陷阱反模式族（Row 吞
   draggable、Form label inline-flex 两栏陷阱、css-in-js 特异性压制、移动端
   「改布局不改宽度」）。
2. **一般域**（默认法，浅色）：overview / projects / settings / help / activities
   ——antd 浅色 token 为基 + 浅灰卡片定制（#f6f6f6/#efefef）。
3. **例外域**（特别法，逐域小节，**结构可扩展**）：每域一节 = 用途声明 + 域专属
   token + 与一般域的偏离清单。首个实例：**大屏域**（command-center 四屏）——深蓝黑
   四色单源（BG `#0a1628` / PANEL_BORDER / TEXT_MAIN / TEXT_SUB）+ 派生色（CARD_BG、
   GREEN_DIM_BG 等，与 `shared.ts` 对齐），用途「大屏展示」。后续可扩移动应用等新域
   （预留结构，不预写内容）。
4. **待裁决段**：普查中无出处的条目，留用户逐条裁决，裁决后经修正案程序入正式条款。

红线段置于文档头部显眼位置（stack_profile 摘录封顶 40 行且按视觉关键词行筛选，头部
红线必须能稳定入选摘录）。

## 4. 普查成文方法（问题 1a）

材料源清单（全部有出处）：

| 材料源 | 内容 |
|---|---|
| `command-center/shared.ts` 常量表 | token 真相源，含定稿日期注记（如「10-29 用户定稿加深」） |
| 已定稿 SPEC 设计文档 | 如 2026-10-28-agent-card-redesign：五段结构/字号阶/红线/用户否决项 |
| 各 SPEC 反目标段 | 「出现即算失败」清单 → do-not 列表 |
| 事故记忆沉淀的 antd 陷阱族 | 上述反模式族四例的原始出处 |
| `.history/` 原型定稿 | 用户逐轮批注的最终形态 |

提取原则：只收「已发生过的用户裁决」，每条标注出处（SPEC 名/定稿日期）；无出处条目
一律进「待裁决段」；文档记录宪法现状，不立新宪。

## 5. 偏离审计方法（问题 1b）

1. **静态代码审计**：以 DESIGN.md 为检查清单扫 dashboard 源码——硬编码色值脱离
   token 白名单、字号脱阶、animation/transition 残留、null 口径、tabular-nums。
   产出「页面 × 违规条目 × 代码证据」清单。
2. **渲染对照**：playwright-cli 命名会话截五屏（避开在飞 run 会话共享），与
   DESIGN.md 视觉对照。
3. **三分类裁决**：
   - (a) 无声明偏离 → 实现走样，改代码（另立修复项）；
   - (b) SPEC 已声明的偏离 → 核对例外域条款覆盖，缺的走修正案补录；
   - (c) 文档本身错/漏 → 走修正案。
4. 审计产物即修正案素材——审计本身是磨准宪法的手段，首轮不追求文档一次写对。

## 6. SPEC 级偏离声明格式

用户明确同意偏离宪法的，SPEC 设计文档必须包含「偏离声明」段：**偏离条目 + 理由 +
适用范围**（哪域/哪屏/哪组件）。审计以「未声明偏离」为真违规判据；已声明偏离核对
例外域条款是否同步覆盖。

## 7. 修正案程序（三步，定案）

1. **用户定稿事件**（原型批准 / SPEC 定稿 / 明示裁决）→ 取得回写**资格**，不自动生效。
2. **AI 提出回写建议**：diff 级提案——新增/修改哪条、放哪个域、出处标注。
3. **用户确认** → AI 执行写入。

Agent 任何时刻无直写权。

## 8. 新界面流程接线（问题 2 定稿）

```
立项（fenix-new）
  ↓ 触发 fenix-prototype
原型生成阶段（双注入）：
  · stack_profile 注入 DESIGN.md 摘录（宪法约束，冲突时宪法赢）
  · frontend-design 两遍式产候选（只填宪法空白处 + 反模板自批判）
  ↓
用户批注迭代 → 定稿 → AI 提回写建议 → 用户确认 → 回写 DESIGN.md
  ↓
implementer 按 SPEC 引用（原型真相源 + DESIGN.md）
```

- **frontend-design 替代 ui-ux-pro-max**（定案依据：frontend-design 的两遍式流程
  原生产出候选 token 系统（命名色值 + 字体角色 + 布局概念 + 签名元素）+ 反 AI 俗套
  自批判，零依赖已装；ui-ux-pro-max 的风格库偏通用 web/营销场景，与 antd 监控大屏
  气质不对齐，其「秒出完整设计系统」卖点在有原型批注环的体系里权重低——真正的定稿
  机制是用户逐轮批注）。仅当未来出现 dashboard 域之外全新界面（如对外宣传页）时再
  评估采纳。
- 复合裁决规则唯一一条：生成器建议与 DESIGN.md 冲突时，DESIGN.md 赢。

## 9. 里程碑建议

- **M1 普查成文**：根 DESIGN.md 初稿（§3 四段结构 + 出处标注 + 待裁决段）。
- **M2 首轮偏离审计**：待裁决段呈报用户裁决 + 静态扫/渲染对照 + 三分类清单。
- **M3 修正案首轮**：按审计素材提 diff 级提案，用户确认后回写，宪法磨准。
- 新界面接线无独立里程碑：stack_profile 消费口已存在，DESIGN.md 落地即生效。

## 10. 留给 builder 的部分

- DESIGN.md 具体行文与条目粒度（对齐 awesome-design-md 成熟格式，紧凑以适配 40 行摘录）。
- 普查的 SPEC 清单化与扫描顺序。
- 审计执行形态（一次性 agent 执行即可，不要求工具化复用）。
- 修正案提案的具体呈现格式（diff 文本 + 出处表）。
