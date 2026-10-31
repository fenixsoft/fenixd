# fenixd 界面设计宪法（DESIGN.md）

本文档是 fenixd 界面设计语言单一事实源，按「通用条款 / 一般域 / 例外域 / 待裁决段」
四段组织（出处：2026-10-31-design-md-governance-design.md 定稿）。修正案三步程序：
用户定稿事件取得回写资格 → AI 提出 diff 级提案 → 用户确认后 AI 写入；agent 任何
时刻无直写权。SPEC 涉偏离宪法须在设计文档写偏离声明段（偏离条目 + 理由 + 适用
范围），审计以「未声明偏离」为真违规判据。本文档只记录现状，不立新宪；每条正式
条款标注出处，无出处条目进待裁决段。

## 红线（全域生效，违反即审计真违规）

- 静态渲染红线：布局与配色一次性静态渲染——禁 CSS animation / transition / SMIL 与
  一切装饰性动效（插画、动画角色、吉祥物），数据更新走重渲染不走动画。（出处：
  spec/archive/2026-10-31-add-command-center specs/command-center-console-ui「无动画
  /插画」Scenario + design.md D6；docs/superpowers/specs/2026-10-25-agent-topology-
  bigscreen-design.md）
- null 口径红线：数据缺口（null / undefined / 口径不可得）一律显示「—」，颜色与
  数字都不得伪装缺口——MUST NOT 显示 0（0 与「口径不可得」语义不同）。（出处：
  command-center-console-ui spec「null 指标 MUST 显示『—』而非 0」+ shared.ts 常量
  表注记）
- 配色单源红线：界面颜色只准取自本宪法 token 表（一般域 antd token，大屏域四色单源
  + 派生色），MUST NOT 散落硬编码新色值。（出处：shared.ts 常量表「集中管理、组件内
  不散落硬编码色值」注记，2026-10-28 LaneCard 重设计定稿）
- 字号与数字排版：数值指标一律 tabular-nums 等宽字体排版，保证纵向可比对齐。
  （出处：shared.ts OrgGrid 注记 2026-10-28 定稿；2026-10-31 定稿 §3.1 收录）
- antd 陷阱红线（反模式族，涉布局 / 表单 / 样式，踩中即返工）：① Row 会吞
  draggable（拖拽交互勿放 Row 内）；② Form label inline-flex 两栏对齐陷阱；
  ③ css-in-js 特异性压制既有样式；④ 移动端视口「改布局不改宽度」。（出处：
  2026-10-31 定稿 §3.1，事故记忆沉淀；④ 另见
  spec/archive/2026-09-13-fix-mobile-breakpoint-hook-tables）

## 通用条款（跨域共享）

- 字号阶纪律：字号只准取自既定阶，MUST NOT 随手夹中间值；具体阶值见待裁决段 #1
  （现状普查已呈报，裁决后经修正案入本条）。（出处：2026-10-31 定稿 §3.1 收录
  「字号阶」为通用条款主题）
- 数据墨水优先：界面以数据为主语，小号标签 + 静态细线 + 高密度排布；灰字走 antd
  token colorTextTertiary，不手写灰色。（出处：command-center-console-ui spec 风格
  条款；app.tsx 注记「灰字走 colorTextTertiary 适配未来暗色主题」）

## 一般域（默认法：overview / projects / settings / help / activities）

- 基线：antd 浅色 token（默认算法）为基，不另起色板；状态色沿用 antd 语义色
  （success / error / warning / info）。（出处：2026-10-31 定稿 §3.2「antd 浅色
  token 为基」定稿）
- 浅灰卡片定制：settings 页卡片底 #f6f6f6、卡头 #efefef。（出处：2026-10-31 定稿
  §3.2 收录；core/dashboard/static/src/global.less settings 页实证；适用范围见
  待裁决段 #2）
- 布局惯例：导航 + 分区卡片 + 表格为主干；页面级抽风风格创新不做，与既有页协调。
  （出处：fenix-dashboard 归档系列定稿现状；2026-10-29-ui-prototype-loop-design.md
  「与画像既有布局惯例协调」）

## 例外域（特别法，逐域小节）

> 每个例外域 = 用途声明 + 域专属 token + 与一般域的偏离清单。新增界面域（如未来
> 移动应用）按同一模板增小节即可，不改通用条款与一般域；MUST NOT 为未出现的域
> 预写内容。

### 例外域：大屏域（command-center 四屏 / collab-graph / spec-topology）

- 用途声明：大屏展示——管理层演示路径（90 秒组织总览 → SPEC 钻取 → 裁决 → 台账），
  远距离投屏可读。（出处：spec/archive/2026-10-31-add-command-center design.md Goals）
- 域专属 token（深蓝黑四色单源，IOC 风格；出处：shared.ts 常量表，与协作图谱/拓扑
  大屏同一色系）：
  - 基色四源：BG `#0a1628` / PANEL_BORDER `rgba(59,110,165,0.4)` / TEXT_MAIN
    `#d6e7f7` / TEXT_SUB `#7f9cba`。
  - 派生色（2026-10-28 LaneCard 重设计定稿族，10-29 用户定稿加深连接线）：
    CARD_BG `rgba(10,30,56,0.55)`、CARD_BG_HOVER `rgba(16,42,78,0.65)`、
    CARD_BORDER_BRIGHT `rgba(94,150,210,0.7)`、ACCENT `#40a9ff`、GREEN `#52c41a`、
    GREEN_DIM_BG `rgba(82,196,26,0.12)`（hover 0.2）、AVATAR_BG 蓝系渐变、
    AVATAR_BORDER `rgba(64,169,255,0.25)`、REST_BORDER `rgba(91,112,140,0.35)`、
    METRIC_DIVIDER `rgba(59,110,165,0.25)`、LINK_STROKE `rgba(94,150,210,0.75)`；
    spec 视图单元格 hover `rgba(64,169,255,0.10)` / 选中 `rgba(64,169,255,0.16)`
    （add-command-center-spec-view 定稿）。
  - 状态语义色：绿 `#52c41a`=成功/运行中；红 `#ff4d4f`=失败/严重；蓝 `#40a9ff`=
    运行中/次要；橙 `#fa8c16`=中断/取消/门禁拦截/重要；灰蓝 `#7f9cba`=空闲/取代/
    失联/空产物。（出处：shared.ts badge 函数族注记，classify_run 口径中文标签）
  - 等宽字体栈：`ui-monospace, 'SF Mono', Menlo, Consolas, monospace`（FONT_MONO）。
- 与一般域的偏离清单：
  1. 配色：深蓝黑四色单源替代 antd 浅色 token（登记为域专属 token，非违规）。
  2. 图表：手写 SVG + React 零图表库；状态色复用 utils/runVisual.ts STATUS_HEX
     单源。（出处：collab-graph-bigscreen design.md D6/D7）
  3. 刷新：固定间隔静默轮询（≥30s 常量），不做实时推送、不加配置项。（出处：
     command-center-console-ui spec）
  4. 静态渲染红线在本域按「汇报线/图表静态 SVG、无任何动画元素」从紧执行。（出处：
     同 spec「静态 SVG、无动画」Scenario）

## 待裁决段（普查无出处条目，留用户逐条裁决；裁决后经修正案入正式条款）

1. 字号阶具体取值：现状普查 fontSize 分布 11/12/13/14/16/18/20/24/28（12 与 14 为
   主力）。提案：12 副文本 / 14 正文 / 16-18 区块标题 / 28 大数值指标，11/13/15/17
   视为脱阶待收敛。（无定稿出处，2026-11 首轮审计现状普查）
2. 浅灰卡片定制 #f6f6f6 / #efefef 的适用范围：现状仅 settings 页实证；是否推广为
   一般域全部页卡统一卡底，待裁决。（无明示范围定稿）
3. tabular-nums 的适用范围：定稿收录为通用条款，但现状仅 command-center OrgGrid 与
   claude-msg ToolCard 实证；一般域浅色页数值列是否全域强制，待裁决。
4. 一般域语义色是否直接沿用 antd 默认 success/error/warning/info 色板（现状 mostly
   是，但无明示裁决），待裁决。

## 附则：修正案程序与偏离声明

- 修正案三步：① 用户定稿事件（原型批准 / SPEC 定稿 / 明示裁决）取得回写资格，不
  自动生效；② AI 提 diff 级提案（新增/修改哪条、放哪个域、出处标注）；③ 用户确认
  后 AI 执行写入。agent 任何时刻无直写权，用户定稿事件本身 MUST NOT 自动触发回写。
  （出处：2026-10-31 定稿 §7；spec/changes/add-design-md-governance governance spec）
- SPEC 级偏离声明格式：偏离条目 + 理由 + 适用范围（哪域/哪屏/哪组件）。已声明偏离
  审计时核对例外域条款覆盖；未声明偏离判真违规进改代码清单。（出处：2026-10-31
  定稿 §6）
