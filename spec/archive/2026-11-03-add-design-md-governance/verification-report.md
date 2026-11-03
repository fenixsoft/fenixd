# 验证报告：add-design-md-governance

> ⚠️ 本报告由框架于 2026-10-31T09:29:24Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-31T09:29:23.707181+00:00+run-result@mtime1793438963755686959

## 结论：✅ 通过（verified）

**状态：verified — 21/21 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 21/21 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 21 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.39M |
| 本链增量 Token（输出） | 0.11M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| design-md-exists-at-root | 仓库根 DESIGN.md 宪法落位验证：文件存在于验证树根且非空（摘录候选路径首位即根 DESIGN.md，根落位才能被 stack_profile 稳定取到）。出处：spec/changes/add-design-md-governance/tasks.md Deliverables（DESIGN.md kind:new）、skills/fenix-prototype/scripts/stack_profile.py:261（_DESIGN_DOC_CANDIDATES 首位 DESIGN.md） | pass | 0/2 | - |
| design-md-four-section-structure | DESIGN.md 四段结构完整且红线置头：红线段 → 通用条款 → 一般域 → 例外域 → 待裁决段 依序齐备（用 awk 行序断言机械化验证「红线类条目 MUST 置于文档头部」），缺段或乱序即结构性违规。出处：specs/design-md-governance/spec.md「DESIGN.md 宪法四段结构」Requirement、DESIGN.md 实际节构（红线:10 / 通用条款:32 / 一般域:41 / 例外域:53 / 待裁决段:88） | pass | 0/7 | - |
| design-md-redlines-content | 红线类条目内容成文：静态渲染红线（禁 CSS animation/transition/SMIL）、null 口径红线（缺口显「—」MUST NOT 显示 0）、配色单源红线、字号与数字排版（tabular-nums）、antd 陷阱反模式族五族红线全部落文，且行文遵循 tasks 1.2 约定（红线条目为标题行或行内含视觉关键词，摘录过滤器才可选中）。出处：specs/design-md-governance/spec.md 四段结构 Requirement 红线置头条款、tasks.md 1.2 行文约定、DESIGN.md:10-30 | pass | 0/9 | - |
| design-md-provenance-discipline | 普查成文出处纪律：正式条款逐条标注出处（「出处：」标注、定稿日期、shared.ts 常量表溯源），无出处条目集中待裁决段（待裁决段明示「普查无出处条目」口径），不混入正式条款。出处：specs/design-md-governance/spec.md「普查成文出处纪律」Requirement、design.md 决策 3（出处纪律=宪法合法性判据）、DESIGN.md:88 | pass | 0/6 | - |
| design-md-bigscreen-exception-domain | 例外域首个实例=大屏域且结构可扩展：大屏域小节含三件套（用途声明「大屏展示」+ 域专属 token 深蓝黑四色单源 + 与一般域的偏离清单），token 与 command-center/shared.ts 常量表对齐；例外域按同一模板扩展新界面域、不为未出现的域预写内容。出处：specs/design-md-governance/spec.md「例外域结构可扩展」「一般域与大屏域并存不冲突」Scenario、design.md 决策 2、core/dashboard/static/src/pages/command-center/shared.ts:7-11（BG #0a1628 等）、DESIGN.md:53-86 | pass | 0/9 | - |
| design-md-amendment-three-step | 修正案三步程序成文：① 用户定稿事件取得回写资格（不自动生效）→ ② AI 提 diff 级提案（改哪条/放哪个域/出处标注）→ ③ 用户确认后 AI 执行写入；agent 任何时刻无直写权、定稿事件 MUST NOT 自动触发回写。出处：specs/design-md-governance/spec.md「修正案三步程序」Requirement（含「定稿事件不自动写入」「确认后写入」Scenario）、design.md 决策 5、DESIGN.md:100-105 | pass | 0/6 | - |
| design-md-deviation-declaration-format | SPEC 级偏离声明格式成文：偏离声明 = 偏离条目 + 理由 + 适用范围（哪域/哪屏/哪组件）；审计以「未声明偏离」为真违规判据、已声明偏离核对例外域覆盖。出处：specs/design-md-governance/spec.md「SPEC 级偏离声明」Requirement（含「已声明偏离合法」「未声明偏离判违规」Scenario）、DESIGN.md:106-108 | pass | 0/5 | - |
| stack-profile-candidate-priority-and-missing | 摘录候选链契约回归（根路径优先 + 缺失空态）：① 临时工程同时含根 DESIGN.md 与 docs/DESIGN.md 时摘录取根路径文件内容（根落位决策的消费面）；② 无任何 DESIGN.md 的空工程摘录为 null 且 CLI 正常退出 0（降级不崩，空态口径）。出处：stack_profile.py:261（候选序 DESIGN.md→docs/DESIGN.md→doc/DESIGN.md）、stack_profile.py:268-288（extract_design_doc 返回 None 契约）、stack_profile.py:370（unknown 画像也携带 design_doc 字段）、design.md Non-Goals（不改 stack_profile.py） | pass | 0/4 | - |
| regression-stack-profile-extract-contract | 回归守卫（摘录过滤契约未被改动凑摘录）：既有单元测试 test_design_doc_extracted 保持通过（红线入选靠 DESIGN.md 行文达成，不靠改过滤器）；stack_profile.py 源码未新增 animation 关键词（_DESIGN_KEYWORD 词表无 animation/transition 是 tasks 1.2 行文约定的前提，给脚本补关键词即属超范围改动）、摘录候选链仍在。出处：tests/test_fenix_prototype.py:88-92（test_design_doc_extracted，非参数化用例）、stack_profile.py:262-265、design.md Non-Goals | pass | 0/5 | - |
| prototype-skill-design-candidate-contract | fenix-prototype 生成契约接线（tasks 2.1）：SKILL.md §3.3「画像主题注入」段内增补设计候选注入契约——DESIGN.md 摘录未覆盖的版式/组件形态遵循 frontend-design skill 两遍式产出候选（仅填补宪法空白 + 反 AI 俗套自批判），并携带本 SPEC 出处标记（add-design-md-governance）。出处：specs/ui-prototype-generation/spec.md「真组件高保真生成」MODIFIED Requirement「宪法空白处产出候选」Scenario、tasks.md 2.1、skills/fenix-prototype/SKILL.md:89-95（§3.3 段内，段界 81-96） | pass | 0/4 | - |
| prototype-skill-constitution-wins-on-conflict | 候选与宪法冲突时宪法赢（tasks 2.1）：SKILL.md 明文候选与 DESIGN.md 摘录冲突时 MUST 以宪法为准（宪法赢）、MUST NOT 用生成器建议覆盖已定稿设计语言，并在生成说明中注明冲突点及采纳宪法的理由；无冲突候选注明候选来源；生成器候选不直接回写宪法。出处：specs/ui-prototype-generation/spec.md「候选与宪法冲突时宪法赢」Scenario、skills/fenix-prototype/SKILL.md:92-95 | pass | 0/6 | - |
| fenix-new-skill-design-md-wiring | fenix-new 起草接线（tasks 2.2）：SKILL.md §1.7「界面改动判定与原型衔接」段内增补设计宪法引用与偏离声明契约——UI 相关 SPEC 起草 MUST 引用仓库根 DESIGN.md 作为设计约束来源；涉偏离 SPEC 的设计文档 MUST 含偏离声明段（偏离条目 + 理由 + 适用范围），未声明偏离判真违规。出处：specs/design-md-governance/spec.md「fenix-new 起草接线」Requirement（UI SPEC 引用宪法/涉偏离 SPEC 带声明段 Scenario）「SPEC 级偏离声明」Requirement、design.md 决策 8、skills/fenix-new/SKILL.md:87-95（§1.7 段内，段界 58-97） | pass | 0/5 | - |
| audit-doc-three-categories | 首轮审计产物落盘且三分类归档（tasks 3.3）：docs/design-md-audit-2026-11.md 存在，含 (a) 无声明偏离→改代码清单（只列不改、修复另立）、(b) 已声明偏离→例外域覆盖核对、(c) 宪法错漏→修正案 三分类清单，审计纪律为只列不改。出处：specs/design-md-governance/spec.md「首轮偏离审计三分类」Requirement、tasks.md 3.3、design.md 决策 4（落 docs/ 不混入 spec/changes）、docs/design-md-audit-2026-11.md:24-54 | pass | 0/7 | - |
| audit-static-scan-dimensions | 静态审计五维检查清单覆盖（tasks 3.1）：审计以 DESIGN.md 为检查清单扫 core/dashboard/static/src/，覆盖硬编码色值脱离 token 白名单、字号脱阶、animation/transition 残留、null 口径、tabular-nums 五维，违规发现含页面×代码证据（file:line 形态真实到具体行）。出处：specs/design-md-governance/spec.md「首轮偏离审计三分类」Requirement、tasks.md 3.1、docs/design-md-audit-2026-11.md:28-41（a-1~a-5 清单含 SessionComposer.tsx:349 等 file:line 证据） | pass | 0/8 | - |
| audit-render-comparison-named-session | 渲染对照留痕（tasks 3.2，成功/降级双分支收口）：审计文档记录渲染对照——成功分支为 playwright-cli 命名会话（-s=design-audit，未占用在飞 run 共享的 default 会话）截 overview/projects/settings/help/command-center 五屏；不可达/受限分支显式标注降级遗留，MUST NOT 静默跳过。出处：specs/design-md-governance/spec.md「渲染对照用命名会话」Scenario、tasks.md 3.2、design.md Risks 降级条款、docs/design-md-audit-2026-11.md:108-116 | pass | 0/6 | - |
| audit-amendment-proposal-no-auto-write | 修正案 diff 级提案呈报且不自动写入（tasks 3.3）：审计文档含 (b)(c) 类 diff 级修正案提案（C1 迁移件豁免/C2 null 口径措辞/C3 字号阶定稿，diff 代码块形态 + 出处表），写入动作明确等用户确认后按修正案三步程序执行、确认前 DESIGN.md 不变——审计产出仅取得回写素材，agent 不借审计直写宪法。出处：specs/design-md-governance/spec.md「修正案提案不自动写入」Scenario、design.md 决策 5、docs/design-md-audit-2026-11.md:54-96、118-123 | pass | 0/7 | - |
| audit-pending-ruling-reported | 待裁决段逐条呈报（tasks 3.3）：审计文档以待裁决表逐条呈报（字号阶取值/浅灰卡片适用范围/tabular-nums 适用范围/语义色板/迁移件豁免），与 DESIGN.md 待裁决段呼应（宪法 4 条 + 本轮新增第 5 条），留用户逐条裁决、裁决后经修正案入正式条款。出处：specs/design-md-governance/spec.md「首轮偏离审计三分类」Requirement（审计产物 MUST 含待裁决段呈报）、DESIGN.md:88-98、docs/design-md-audit-2026-11.md:98-106 | pass | 0/7 | - |
| web-general-domain-overview-renders | 一般域（默认法）overview 页回归渲染：宪法一般域浅色 antd token 域的核心页 overview 在文档层变更后照常渲染，页头「跨项目概览」在位、无控制台错误——宪法↔现实对照的回归面（一般域默认法不受影响）。出处：core/dashboard/static/config/routes.ts:11（/overview 路由注册）、core/dashboard/static/config/config.ts:15（history hash 路由）、core/dashboard/static/src/pages/overview/index.tsx:208（PageContainer title 跨项目概览）、core/dashboard/registry.py:33（DEFAULT_PORT 8787） | pass | 0/3 | - |
| web-general-domain-settings-renders | 一般域（默认法）settings 页回归渲染：宪法一般域浅色页 settings 在文档层变更后照常渲染，页尾保存按钮（data-testid=settings-save）可见且可用——宪法↔现实对照的回归面。出处：core/dashboard/static/config/routes.ts:47（/settings 路由注册）、core/dashboard/static/config/config.ts:15（hash 路由）、core/dashboard/static/src/pages/settings/index.tsx:546（data-testid=settings-save，仅 self-evolution 页签渲染，settings/index.tsx:528-551；默认页签 llm 需先点击自进化页签）、core/dashboard/registry.py:33（DEFAULT_PORT 8787） | pass | 0/3 | - |
| stack-profile-excerpt-includes-head-redlines | 红线入选 stack_profile 摘录（tasks 1.2 验证条款逐字执行）：对验证树跑 python3 skills/fenix-prototype/scripts/stack_profile.py --project . --pretty，输出的 design_doc.path 指向根 DESIGN.md 且摘录包含头部红线条目（静态渲染红线/null 口径红线/配色单源红线/tabular-nums）——证明红线置头+行文约定能稳定入选 40 行封顶摘录、可注入原型生成 prompt。命令全仓受控遍历，timeout 放宽 300s。出处：specs/design-md-governance/spec.md「红线入选 stack_profile 摘录」Scenario、tasks.md 1.2、stack_profile.py:261-288（标题行无条件入选∪视觉关键词行，封顶 40 行；实测摘录 23 行含全部五族红线） | pass | 0/6 | - |
| web-bigscreen-domain-coexist | 一般域与大屏域并存回归对照：同一实例同一会话内先访浅色 overview 再入深蓝黑大屏 command-center，三页签（组织总览/交付流水线/执行台账）照常渲染——印证宪法例外域登记的大屏域与一般域并存不冲突（文档层变更零运行时影响的回归面）。出处：core/dashboard/static/config/routes.ts:26（/command-center 路由）、core/dashboard/static/config/routes.ts:11（/overview 路由）、core/dashboard/static/src/pages/command-center/index.tsx:182-210（三 Tab label 组织总览/交付流水线/执行台账）、core/dashboard/static/config/config.ts:15（hash 路由）、core/dashboard/registry.py:33（DEFAULT_PORT 8787） | pass | 0/5 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

