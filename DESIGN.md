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
- null 口径红线：数值 / 指标类数据缺口（null / undefined / 口径不可得）一律显示
  「—」，颜色与数字都不得伪装缺口——MUST NOT 显示 0（0 与「口径不可得」语义不同）；
  文本型未知值可用中文限定词（「未知 run」「时长未知」），不强制「—」。（出处：
  command-center-console-ui spec「null 指标 MUST 显示『—』而非 0」+ shared.ts 常量
  表注记；2026-10-31 用户裁决 C2 措辞澄清，首轮审计文本占位核对）
- 配色单源红线：界面颜色只准取自本宪法 token 表（一般域 antd token + 宿主对齐
  覆盖表，实现单源 core/dashboard/static/src/theme.ts；大屏域四色单源
  + 派生色，实现单源 shared.ts 常量表），MUST NOT 散落硬编码新色值。（出处：
  shared.ts 常量表「集中管理、组件内不散落硬编码色值」注记，2026-10-28
  LaneCard 重设计定稿；一般域 theme.ts 单源指针为 2026-11-03 宿主对齐改造
  增补）
- 字号与数字排版：数值指标一律 tabular-nums 等宽字体排版，保证纵向可比对齐；
  适用范围全域强制（含一般域浅色页数值列，存量缺样式的列补
  fontVariantNumeric，列改代码清单）。（出处：shared.ts OrgGrid 注记 2026-10-28
  定稿；2026-10-31 用户裁决 #3 全域强制，首轮审计 a-5）
- antd 陷阱红线（反模式族，涉布局 / 表单 / 样式，踩中即返工）：① Row 会吞
  draggable（拖拽交互勿放 Row 内）；② Form label inline-flex 两栏对齐陷阱；
  ③ css-in-js 特异性压制既有样式；④ 移动端视口「改布局不改宽度」。（出处：
  2026-10-31 定稿 §3.1，事故记忆沉淀；④ 另见
  spec/archive/2026-09-13-fix-mobile-breakpoint-hook-tables）
- 迁移件豁免：经用户裁决豁免的第三方迁移组件族保留其原视觉语言，不适用静态渲染
  红线；豁免族清单在本条登记，新迁移件入族须走修正案程序。现有豁免族：
  claude-msg / claude-composer（迁移自 claudecodeui，含 tailwind transition-* 类）。
  （出处：2026-10-31 用户裁决 C1 豁免；首轮审计 a-1 发现；SessionComposer.tsx:2-4 /
  ToolCard.tsx:1-2 迁移注记）

## 通用条款（跨域共享）

- 字号阶纪律：字号只准取自既定阶 11 / 12 / 13 / 14 / 16 / 18 / 28（11-12 副文本 /
  13-14 正文 / 16-18 区块标题与强调 / 28 大数值指标），MUST NOT 随手夹 15 / 17 /
  20 / 24 等阶外值（存量脱阶散值合计 6 处，列改代码清单收敛）。（出处：2026-10-31
  用户裁决 #1 宽阶定稿；现状普查 scan-type-null.txt，首轮审计）
- 数据墨水优先：界面以数据为主语，小号标签 + 静态细线 + 高密度排布；灰字走 antd
  token colorTextTertiary，不手写灰色。（出处：command-center-console-ui spec 风格
  条款；app.tsx 注记「灰字走 colorTextTertiary 适配未来暗色主题」）
- Bento 磁贴圆角固定 12px：凡 Bento 磁贴形态的白磁贴（v2 六页 `.v2-bento`、现产
  overview 统计卡与项目台账磁贴 `.ov-bento` 及后续同语态新增面），border-radius
  一律 12px，MUST NOT 回调 16px 或逐页散值；胶囊徽标 999px 不变，一般域 antd
  控件圆角 6/4/8 条款不受影响（本条是磁贴形态级规则，非 theme 级 borderRadius
  覆写）。（出处：2026-11-06 用户指令「border-radius 从 16px 改为 12px，作为
  固定规则写入 DESIGN.md」，overview 台账对齐 v2 改造中提出，全站统一适用；
  实现单源 pages/v2/theme.tsx `V2_TILE_RADIUS` + v2.less 镜像 + global.less
  overview 镜像）。**灰底准例（仅配置页）**：settings 卡片经同日用户指令准离
  本条——圆角 10px + 边框加深 #d7d7d7（浅灰卡底 #f6f6f6 上 #eef2f7 发丝线
  不可辨，边框不可见即失效），MUST NOT 推广至白底磁贴页。

## 一般域（默认法：overview / projects / settings / help / activities）

- 基线：antd 浅色 token 算法为基，ConfigProvider 挂「宿主对齐覆盖表」（实现面
  theme.ts 常量单源）。覆盖表逐键注明 dsw 源键：主色黑系 #0f1115（dsw
  alias-brand-primary=neutral-bluish-1000，hover #43454a=bluish-750）、链接与
  info #4176e6（deepseek-500——蓝只留给链接、输入焦点、info 语义）、状态色
  success #22c55e / error #ec1313 / warning #f59e0b（dsw state-success/error/
  warn-primary）、文字四阶 #0f1115 / #61666b / #81858c / #adb2b8（dsw
  label-primary/secondary/tertiary/caption）、边框黑 alpha 0.16 与 0.10（dsw
  border-l4/l2）、圆角维持 antd 默认值 6 / 4 / 8（2026-11-03 用户裁决：不引入
  dsw radius 阶，卡片与控件还原 antd 原圆角；首版曾挂 12/8/16 与 Tag 胶囊
  999px，同日撤回；theme.ts 注明 MUST NOT 挂 borderRadius 覆写）、控件高
  32 / 28
  （dsh 基元 Input 32px、Button sm 28px）、输入焦点蓝 + 蓝光圈（dsw
  Input.module.css focus=state-business-primary）、Table 表头 bluish-50 底 +
  次级文字（dsw markdown-table-head 语义）、Tag 胶囊 999px（dsw Tag 基元）、
  Menu 行高 36 + 选中冷灰 rgba(38,49,72,0.10)（dsh 侧栏行基线与交互底）。
  页面标题 18px/700（字号阶 16-18 档；antd PageContainer 默认 20px 为阶外值）；
  字体栈逐字对齐 dsw-font-family（中文回退前移，global.less 与 theme.ts 同源）。
  （出处：2026-11-03 用户指令「dashboard 嵌入 dsh web 无割裂感」宿主对齐改造；
  token 源=@deepseek-ai/dsh-client-ui-theme 0.2.0-rc.2 --dsw-* alias 表 +
  dsh-client-ui-primitives 基元 CSS。原条款「状态色沿用 antd 语义色默认值」
  （2026-10-31 用户裁决 #4）被本条覆盖：语义色仍走 antd token 通道，值域换轨
  dsh state palette）
- 数据编码色豁免：SPEC / 用户指定的数据编码色不随宿主对齐换轨——「同 ramp、
  空条可辨」等指定语义优先于 UI chrome 对齐。现有豁免：进度条阶段 ramp
  （progressPhase.ts TRACK_LIGHT impl 蓝 #1677ff / GATES gates 橙 / TRACK_GREEN
  verify 绿 / TRACK_CYAN 出题青，含 ProjectCards.tsx 同族）、agent 分类色板
  （IntroduceRow.tsx AGENT_PALETTE，图表可辨色相）、runVisual.ts STATUS_HEX
  （大屏域 utilities）。新数据编码色入本清单登记。（出处：2026-11-03 宿主
  对齐改造裁决；原指定出处见各文件注记——TRACK_GREEN 用户指定色、GATES_STROKE
  spec 任务 5.1 指定色）
- 浅灰卡片定制：settings 页卡片底 #f6f6f6、卡头 #efefef；适用范围明示仅 settings
  页，不推广一般域，其余页维持 antd 默认卡底。（出处：2026-10-31 定稿 §3.2 收录；
  core/dashboard/static/src/global.less settings 页实证；2026-10-31 用户裁决 #2）
- Radio 按钮组激活态固定黑底白字：并排 Radio 过滤控件（optionType="button"，
  现存消费面=overview 运行态筛选、projects 类型/归档过滤，后续同语态过滤组
  一律沿用）激活项一律黑底白字 #0f1115（= 一般域主色黑系 / v2 V2_PRIMARY），
  非激活项保持 antd 描边态；MUST NOT 回退 antd 缺省激活底或逐页散值覆写。
  实现单源 global.less `.ov-radio-dark` 覆写类（Radio.Group 挂类即得）。（出处：
  2026-11-06 用户指令「参考 overview 的 radio 控件样式处理，并将该样式写入
  DESIGN.md」——projects 过滤组对齐 overview 时升格为一般域条款）
- 布局惯例：导航 + 分区卡片 + 表格为主干；页面级抽风风格创新不做，与既有页协调。
  （出处：fenix-dashboard 归档系列定稿现状；2026-10-29-ui-prototype-loop-design.md
  「与画像既有布局惯例协调」）
- 页面内容区间距：滚动页内容区**左右留白 15px**（单源 theme.ts dshLayoutToken
  `paddingInlinePageContainerContent`；pro-layout 缺省回填 `||40` 会吞 0 值，
  生效靠对象尾部 spread 传导）；内容区**顶呼吸带 16px**（顶栏/标题行与首卡之
  间的垫高，页级标记类 + `:has()` 作用于 ant-layout-content，现存消费面=
  overview-page、spec-detail-page 两页；embed 行壳位档豁免归零、下游
  PageContainer 改垫 24px 防 sticky 起滚位移）。MUST NOT 逐页自带第二留白源或
  散落第二套顶垫数值。（出处：左右 15px=2026-11-04 内容区留白治理；顶呼吸带
  16px=2026-11-05 用户指令 overview 顶垫，2026-11-06 用户指令「参考 overview
  界面修改并将页面上、左右间距的数值写入 DESIGN.md」推广至 SPEC 详情页并升格
  本条款）
- SPEC 列表页移动端内容区背景 #e3e3e3：<768px 时 SPEC 列表页（projects DevTab
  移动编排分支）内容区底色取 #e3e3e3（单源 theme.ts `SPEC_LIST_MOBILE_BG`），
  灰底衬托白磁贴卡列表；MUST NOT 扩散到其它页面或桌面分支（桌面内容区零改动，
  由 add-spec-list-mobile-style 桌面零改动守卫钉住）。本值不在上文 token 表内，
  为**已登记偏离色**——改值须同走本附则修正案程序并同步 theme.ts 单源与
  spec/changes/add-spec-list-mobile-style design.md 偏离声明。（出处：2026-11-06
  用户原型批注指定色值 #E3E3E3 + add-spec-list-mobile-style SPEC 定稿）

## 例外域（特别法，逐域小节）

> 每个例外域 = 用途声明 + 域专属 token + 与一般域的偏离清单。新增界面域（如未来
> 移动应用）按同一模板增小节即可，不改通用条款与一般域；MUST NOT 为未出现的域
> 预写内容。

### 例外域：大屏域（spec-topology 拓扑大屏）

> 2026-11-04 用户指令：指挥中心（command-center 四屏）黑改白并去脱壳改
> ProLayout 内容区嵌入，退出本域回归一般域（配色单源改挂 theme.ts dsh 对齐
> 常量表，见 pages/command-center/shared.ts；Agent 卡缩宽 90% 随嵌入）。
> collab-graph 协作图谱大屏此前已删除（commit 3f16acc7e）。原「深蓝黑四色
> 单源」域专属 token 表随指挥中心迁移一并退役，历史值见
> spec/archive/2026-10-31-add-command-center。本域现余成员=SPEC 协作拓扑
> 大屏一项。

- 用途声明：大屏展示——SPEC 全生命周期协作拓扑远距离投屏可读；layout:false
  脱壳全屏深色页。（出处：spec/archive/2026-10-30-add-spec-topology-bigscreen）
- 与一般域的偏离清单：
  1. 配色：深底暗色页替代白底；状态语义色复用 utils/runVisual.ts STATUS_HEX
     单源（与 SpecTimeline 同源）。（出处：add-spec-topology-bigscreen design
     D6/D7）
  2. 图表：手写 SVG + React 零图表库。（出处：同上）
  3. 刷新：SSE 热更新 + 30s 轮询兜底（detail.tsx 同款），不走一般域心跳口径。
     （出处：pages/projects/topology/index.tsx）
  4. 静态渲染红线在本域按「管线/泳道图表静态 SVG、无任何动画元素」从紧执行。
     （出处：specs/topology-bigscreen-ui「静态 SVG、无动画」Scenario）

### 例外域：v2 商业化界面域（redesign-dashboard-v2-ui）

> 2026-11-05 立项的 Bento 磁贴设计语言域，开发期与既有页面并存（全部挂 /v2/
> 路由前缀，D1 路由隔离：v2 条目不写 name/icon，现产侧栏菜单/页头零污染）。
> UI 真相源 = spec/changes/redesign-dashboard-v2-ui/prototype/ 六张定稿原型；
> 是否切换为默认界面由用户另行裁决（验收后另行立项），本域条款仅约束 v2 六页。

- 用途声明：商业化观感的 Bento 磁贴界面（浅灰页底 + 白磁贴 + 黑主色按钮 + 蓝
  链接），覆盖概览 / 项目 / SPEC 详情 / 配置 / 帮助 / 运维六页。（出处：
  spec/changes/redesign-dashboard-v2-ui proposal/design；prototype/variant-b-bento.html
  等六张）
- 域专属 token 表（主题单源 core/dashboard/static/src/pages/v2/theme.tsx，v2 域
  外任何页面不得引用）：
  1. 主色：黑 #0f1115（hover #43454a / active #2c2c2e）；链接蓝 #4176e6。
  2. 底色：页底浅灰 #f8fafc；磁贴纯白 radius 12 软阴影（2026-11-06 用户指令自 16
     改 12，升通用条款固定规则，见「Bento 磁贴圆角固定 12px」）；胶囊 radius 999。
  3. 语义色：success #22c55e / error #dc2626 / warning #d97706；胶囊软色板
     （good 绿软 / warning 琥珀软 / critical 红软 / info 蓝软 / muted 灰蓝软 /
     aqua 青）。
  4. 数据编码 ramp：出题青 #0891b2 / 实现蓝 #2563eb / 门禁橙 #ea580c /
     验证绿 #16a34a；车道色板 V2_LANE_COLORS（堆叠条数据编码）。
  5. 数字排版：tabular-nums（.v2-num）；表格 fixed 布局 + 首列 14px 缩进 +
     长注释 pre-wrap（.v2-bento-table）。
- 与一般域的偏离清单：
  1. 圆角：磁贴 12（2026-11-06 用户指令自 16 改 12，单源升通用条款「Bento 磁贴
     圆角固定 12px」）/ 胶囊 999（一般域 antd 默认 6/4/8）。（出处：本 SPEC design
     偏离声明表；prototype 定稿；radius 值修正见通用条款出处）
  2. 配色单源换轨：v2 主题独立文件，零 import 现产 theme.ts dsh 表。（出处：
     design D2）
  3. 页底浅灰 #f8fafc 替代白底。（出处：design 偏离声明表）
  4. 语义色 error #dc2626 / warning #d97706（原 dsh #ec1313/#f59e0b）。（出处：
     同上）
  5. 标题栏形态：六页自绘标题带（22px/700 大标题 + 返回箭头 + 状态/模式徽标 +
     右侧富组合），不套用全站统一标题栏形态基准。（出处：design 偏离声明表）
  6. 布局承载：v2 页跳过 PageContainer，V2Page 壳自带全出血页底与 24px 内容
     边距（.v2-inner 1400px 居中），一般域「导航 + 卡片主干」布局惯例在磁贴
     网格形态下重新表达。（出处：prototype 各页 main 形态；pages/v2/shared.tsx）
  7. 数据复用：一切数据面（overview/alerts/specs/config/chain/help）复用现产
     /api/ 端点与口径（statusMeta 归族、验证计数、耗时格式、告警裁决
     useAlertAdjudication 闭环），不新建后端；缺口字段渲染「—」不伪装 0，
     无数据源的分面（自愈记录）渲染占位说明。（出处：design D3 + Risks）
  8. 刷新：30s 心跳轮询，不接现产 SSE 合帧（开发期简化口径，页面为与现产
     并行的独立界面）。（出处：pages/v2/overview.tsx 等实现注记）

## 待裁决段（普查无出处条目，留用户逐条裁决；裁决后经修正案入正式条款）

- 宿主暗色主题联动缺口（2026-11-03 宿主对齐改造时登记，非样式条款、系立项
  候选）：dsh web 有 Light / Dark / System 三态主题，面板桥 iframe src 不携带
  主题参数、dashboard 恒浅色渲染——宿主切暗色主题时主面板出现白底割裂。
  治理需跨仓两改（桥传主题 + dashboard antd dark algorithm 适配），是否立项
  待用户裁决；裁决前 dashboard 按浅色单主题维护。（出处：2026-11-03 探索
  dsh-client-ui-theme 亮暗双 alias 表 + embedMount.ts 仅 embed/apiBase 双参实证）

（首轮 4 条已于 2026-10-31 经用户裁决转入正式条款，见各条出处注记；后续审计
新发现的无出处条目按本段机制继续登记。）

## 附则：修正案程序与偏离声明

- 修正案三步：① 用户定稿事件（原型批准 / SPEC 定稿 / 明示裁决）取得回写资格，不
  自动生效；② AI 提 diff 级提案（新增/修改哪条、放哪个域、出处标注）；③ 用户确认
  后 AI 执行写入。agent 任何时刻无直写权，用户定稿事件本身 MUST NOT 自动触发回写。
  （出处：2026-10-31 定稿 §7；spec/changes/add-design-md-governance governance spec）
- SPEC 级偏离声明格式：偏离条目 + 理由 + 适用范围（哪域/哪屏/哪组件）。已声明偏离
  审计时核对例外域条款覆盖；未声明偏离判真违规进改代码清单。（出处：2026-10-31
  定稿 §6）
