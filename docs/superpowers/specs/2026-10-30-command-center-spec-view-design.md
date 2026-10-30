# 指挥中心 spec 视图显示模式（Command Center Spec View）设计文档

日期：2026-10-30
状态：已过 builder 可建性审查；含用户两项裁决（10-30：specView 深链进 URL、轮次全史编号）。待用户确认文档后 /fenix-new 立项

## 1. 背景与意图

指挥中心「组织总览」屏（`core/dashboard/static/src/pages/command-center/OrgGrid.tsx`）现有实时模式：产品团队汇总卡第一格「需求数量」（`summary.spec_count`）只是数字，车道卡活动区只显示在飞归属（attributables）。

用户（10-30）提出新增一种**显示模式**：点击「需求数量」弹出下拉菜单列出当前时间窗内的 spec 名单，选中后全板进入「spec 视图」——每张车道卡活动区切换为该 spec 的轮次视角（该车道在此窗内对该 spec 的每一轮 run），点击任一轮打开该轮对话记录。用途：按 spec 维度横向审视全组织（五线各车道）对同一需求的分工过程。

前置事实：车道卡 2026-10-28 重设计五段结构、2026-10-29 活动行多 spec 并行限高滚动 + 点击 spec 名开 RunRecordModal，均已落地；本设计在其上叠加模式切换，不推翻既有结构。

## 2. 目标 / 非目标 / 反目标

### 目标

1. 「需求数量」格可点击：弹出下拉（搜索 + 滚动列表）列出当前时间窗内活跃 SPEC 名单（项目筛选 × 窗口过滤同 `spec_count` 现口径）。
2. 选中 spec 后全板进入 spec 视图：每张车道卡活动区按车道分别渲染该 spec 的轮次列表或「未运行」。
3. 轮次可点击打开该轮 run 的对话记录（复用 RunRecordModal，与 10-29 活动行点击同款）。
4. 再点「需求数量」退出 spec 视图回实时模式（用户 10-30 定稿退出方式）。
5. spec 视图下 60s 轮询照常，轮次列表随刷新更新。

### 非目标（本轮不做）

- 轮次行不显示 run 状态（done/error/running 徽标）——只显「第 N 轮」，点击开弹窗自见分晓。
- 不改车道卡其余四段（头行/三格指标/sparkline/页脚）在 spec 视图下的内容与口径——状态徽标、指标保持实时语义。
- 不做按 spec 的成本/时长聚合新指标。
- 不改花名册、分区、汇报线、其余三屏（PipelineBoard/ExecutionLedger/AdjudicationInbox）。
- 不做移动端专项适配（与既有大屏口径一致）。
- planner 车道不为 spec 视图造轮次：fenixd 需求人工提、planner 无真实 run 产物（10-28 定稿的派生计数只进指标不产 run），spec 视图下诚实显「未运行」。

### 反目标（出现即算失败）

- 伪造数据：给 planner 或任何无 run 车道造出轮次条目。
- 破坏既有实时模式任何行为（attributables 三分渲染、点击开弹窗、指标 null→「—」红线）。
- org 既有响应键语义变动（只允许新增 `summary.specs`，既有键一律不动）。
- spec 视图列表 DOM 内出现 CSS animation/transition（静态渲染红线；antd Popover/Modal 自身开箱动画与全站既有口径一致，不算违规——既有 RunRecordModal 即 antd Modal）。
- `shared.ts` 引入 react/antd import（node --test type-stripping 直载红线）。

## 3. 交互规格

### 3.1 入口与下拉

- 团队汇总卡「需求数量」格（现 `MetricCell`，`windowLabels(win).teamSpecs`）：加可点击形态——`cursor: pointer` + hover 提亮（对齐车道卡 hover 口径纯色切换）+ 视觉暗示（builder 裁量，如值下加 dotted 下划线一类轻量暗示）；再点一次 = 退出（toggle 语义）。
- 下拉形态：antd Popover 锚定该格，内含搜索框（前端本地过滤，无需防抖后端）+ 滚动列表（最大高度内滚动）。
- 名单条目：`{project, spec}` 对；**全部项目视图显示 `project/spec`**（跨项目同名消歧），单项目视图只显 spec 名。排序按 SPEC created 新→旧。
- 选中即进入 spec 视图并收起下拉；重复选中同一 spec = 无变化（已选中态再点需求数量是退出，不是重选）。

### 3.2 spec 视图下车道卡活动区

选中态记为 `(spec_project, spec)` 二元组。每张车道卡活动区替换为：

- **该车道在该窗内有此 spec 的 run**：限高滚动列表（复用 `.cmdcenter-lanescroll` 深色滚动条与现有容器样式，maxHeight ≈75px），每行一条：
  - 文案 `spec名 · 第N轮`（spec 名与轮号；格式细节 builder 裁量，如 `fix-x · 第3轮`）；
  - **排序最新在前**（started 降序，对齐 attributables 列表习惯），**编号为全史口径（2026-10-30 用户定稿）**：「第N轮」= 该车道对该 spec 全部历史轮次按 started 正序的序号（第1轮=全史最早一轮），窗内只显示落在窗内的轮——7d 窗内 3 轮可显示 第10/11/12轮。序号由后端 `seq` 字段下发，前端零推导；
  - 点击行 → `RunRecordModal(run_id, spec_project)`，与 10-29 活动行点击同款（含 hover 提亮、run_id 缺失禁点兜底——后端保证下发 run_id，此前端兜底仍保留）；
  - 在飞轮次（running/empty）照常入列、照常可点开（与现 attributables 点击在飞 run 同语义）。
- **无 run**：灰虚线框「未运行」（`REST_BORDER` 同族虚线框样式，与 idle「待命 · 等待信号」视觉同族、文案区分），不可点击。
- spec-runs 请求进行中/失败的形态：沿用 `useScreenResource` 既有口径——失败保留上轮数据 + 内联提示由屏级 Alert 承担（既有后台刷新失败模式）；首载未到数据时活动区显「加载中」占位文字（builder 裁量具体形态，须与卡片风格同族、无动画）。

### 3.3 退出与状态联动

- **显式退出**：再点「需求数量」→ 取消选中 → 全板回实时模式（URL 同步清除 spec 参数）。
- **隐式退出**：选中态下切换项目筛选或时间窗后，若所选 `(spec_project, spec)` 不在新名单（org 响应 `summary.specs`）中，自动退出 spec 视图。在前则保持选中。
- **深链（2026-10-30 用户定稿：进 URL）**：选中态提升到 `index.tsx` 与 project/window 同款 URL 同步——参数 `spec`（SPEC 名）+ `spec_project`（该 spec 所属项目，恒随选中入链；单项目筛选下与 project 同值属有意冗余，消歧零歧义）。刷新/分享链接直达 spec 视图；直达链的 spec 经名单校验不过（同隐式退出规则）时清参数回实时模式。antd Tabs 非激活页签不销毁，切屏保持选中天然成立。
- 切到其余三屏再切回：选中态保持（深链落定后不再是裁量点）。

## 4. 后端规格

### 4.1 org 响应扩展（`aggregate_org`）

`summary` 块新增 `specs` 键：`[{project, spec}]`，即现 `spec_count` 统计循环的同窗名单化（同一循环顺手派生，不另扫盘）：

- 窗口过滤与 `spec_count` 完全同口径（parse_state 活跃 SPEC、created 落窗；`all` 窗 created 缺失/脏值仅全量窗计入的现规则一致跟随）；
- 排序 created 新→旧（created 缺失垫底）；每条目 `{project, spec}`；
- 既有 `spec_count` 数值键原样保留。

### 4.2 新端点 `GET /api/command-center/spec-runs`

查询参数：`project`（**必填**，spec 所属项目——下拉条目自带 project，选中即已消歧到单项目；寻址语义复用 `_command_center_scope` 既有口径，未知/不存在项目 200+error 字典）、`spec`（必填，SPEC 名）、`window`（可选 today/7d/all，缺省 today，非法值回落 today，与 org 同规则）。

响应：

```json
{
  "project": "...", "spec": "...", "window": "today",
  "lanes": [
    {"lane": "judge", "zone": "质量线", "rounds": [
      {"seq": 5, "run_id": "...", "started_ts": "...", "inflight": false}
    ]}
  ]
}
```

- `lanes` 为花名册全量出列（零 run 车道也带 `rounds: []`，与 org 卡集合同序同全集：ROSTER 序 + 花名册外观测 lane 殿后；LANE_ALIASES 归并同口径）。
- 轮次收集两步（全史编号 2026-10-30 用户定稿）：①**全史定序**——不限窗收集该（车道归并 LANE_ALIASES 后）× 该 spec 的全部 run（扫 live+archive 全量产物，不套 org 的 14 日 mtime 粗筛；archived_names 剔除同口径保留——选中的是活跃 SPEC 时天然无影响），按 started 升序编 `seq`（1=全史最早）；②**窗内出列**——仅 `started ≥ win_start`（today/7d）或全史（all）的轮进入响应，输出数组按 started 降序（最新在前）。单项目单 spec 全史扫描成本可接受（get_runs 既有 memo 元数据）。started 解析失败的行跳过（无排序键不硬造轮次、不占 seq）。
- `inflight` 布尔 = run status ∈ IN_FLIGHT_STATUSES（读侧判定下发，前端不再自行推断）。
- 纯只读：遵守本模块「不新增 POST 端点」既有约定；路由注册沿用 `command_center_routes.py` 表驱动追加既有形态。

## 5. 前端规格

- `services/dashboard.ts`：新增 `commandCenterSpecRuns(project, window, spec)` + 响应类型（对齐 `commandCenterOrg` 既有形态）。
- `index.tsx`：specView 选中态提升至此，与 project/window 同款 URL 同步（`spec` + `spec_project` 两参数，写读单点；2026-10-30 用户定稿深链），下发 OrgGrid。
- `OrgGrid.tsx`：消费 specView props；团队卡需求数量格包 clickable wrapper（toggle 回写深链）；下拉（Popover + Input 搜索 + 滚动列表）数据源 = `data.summary.specs`（前端本地过滤）。
- spec-runs 拉取：`useScreenResource`（`active` = 屏激活 && specView 非空，`refreshKey` = `project|win|spec`），自带 60s 轮询与序号防乱序，与既有口径零偏差。
- 车道卡活动区：`LaneCard` 增加可选 spec 视图 props（选中时传该卡 `rounds` 或 `null`=未运行/加载中）；实时三分渲染逻辑（`activityLineState`）不动，spec 视图是并列的新渲染分支。
- 实现风格：React inline style 对象（对齐 OrgGrid 现有零 CSS 文件风格）；纯函数（如轮次行状态判定）进 `shared.ts` 并配套 node --test 用例进 `tests/commandCenter.test.mjs`。

## 6. 约束（红线，违反任一即返工）

1. **静态渲染红线**：spec 视图列表 DOM 内禁 animation/transition/SMIL；antd Popover 开箱动画不算违规（与既有 antd Modal 全站口径一致）。
2. **org 兼容红线**：`aggregate_org` 既有键（含 `summary.spec_count`）语义零变动，仅新增 `summary.specs`。
3. **shared.ts 纯度红线**：禁 react/antd import。
4. **零伪造红线**：无 run 车道显「未运行」，任何车道不得出现无 run_id 撑腰的轮次条目（前端 run_id 缺失禁点兜底保留，仅为旧后端形态防御）。
5. **窗口口径红线**：spec 名单与轮次「窗内出列」的窗口/归档剔除过滤必须与 org 既有同口径函数复用（`parse_state`/archived_names/窗口判定同源），不得另写第二份过滤逻辑；spec-runs 全史定序的不限窗扫描是编号口径的有意例外（2026-10-30 用户定稿），不视作违规。
6. 色系沿用大屏四色单源与既有派生色常量，新增色（如选中态提示）进 `shared.ts` 同源管理。

## 7. 验收 Scenario（数值/分支以本节为准）

- Scenario: 下拉名单窗过滤 — Given window=7d、项目 fenixd 7 日内创建 3 个活跃 SPEC、另有 1 个更早创建 When 点「需求数量」Then 列表恰 3 条、按 created 新→旧、无归档 SPEC 混入。
- Scenario: 跨项目同名消歧 — Given project=''（全部团队）且 A、B 项目各有活跃 `fix-x` When 打开下拉 Then 两条 `A/fix-x`、`B/fix-x` 均可选中。
- Scenario: 轮次列表 — Given judge 对 spec-x 窗内 5 轮（t1<…<t5）When 选中 spec-x Then judge 卡活动区限高滚动列表 5 行，顶行 `spec-x · 第5轮`、底行 `第1轮`，点击第3轮行打开 RunRecordModal(run_id=第3轮 run)。
- Scenario: 未运行 — Given ocr 窗内从无 spec-x run Then ocr 卡活动区灰虚线框「未运行」、不可点击。
- Scenario: 在飞轮次 — Given implementer 正跑 spec-x（run 在飞）Then 列表含该轮（inflight=true）、可点击打开运行记录。
- Scenario: 退出 — Given spec 视图选中 spec-x When 再点「需求数量」Then 全板回实时模式，活动区恢复 attributables/执行中/待命三分。
- Scenario: 切窗自动退出 — Given 选中 spec-x（7d 窗选中）When 切 window=today 且 spec-x 非 today 创建 Then 自动退出 spec 视图。
- Scenario: planner 诚实口径 — Given planner 无真实 run 产物 Then spec 视图下显「未运行」，不出现派生计数轮次。
- Scenario: 静态红线 — Then spec 视图轮次列表 DOM 无 `animation`/`transition` 属性字样。
- Scenario: 全史编号 — Given code-fix 对 spec-y 全史 10 轮、today 窗内仅 1 轮 When 选中 spec-y Then 该轮显示 `spec-y · 第10轮`（非「第1轮」）。
- Scenario: 深链直达 — Given URL 携带 `spec=spec-x&spec_project=A` 且 `A/fix-x` 在当前窗名单 When 进入组织总览 Then 直接处于 spec 视图；Given spec 参数不在名单 Then 清参数回实时模式。

## 8. 留给 builder 的部分

- Popover 定位/宽度、搜索框与列表滚动细节、需求数量格可点击态的具体视觉暗示。
- spec-runs 首载占位与失败降级的具体形态（§3.2 约束内裁量）。
- 前端类型与纯函数拆分（如轮次行 label 组装、选中态匹配 `summary.specs` 的判定）。
- 里程碑拆分（建议后端 4.1+4.2 一轮、前端一轮，或单轮全做；预估触点：`command_center.py`、`command_center_routes.py`、`services/dashboard.ts`、`index.tsx`、`OrgGrid.tsx`、`shared.ts`、后端 `tests/test_command_center_aggregation.py`、前端 `core/dashboard/static/tests/commandCenter.test.mjs`——builder 审查勘误：前端测试在 static/tests/ 下，非仓根 tests/）。
