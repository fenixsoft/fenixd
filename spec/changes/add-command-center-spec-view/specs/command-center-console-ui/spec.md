## ADDED Requirements

### Requirement: spec 视图显示模式

组织总览屏 MUST 新增 spec 视图显示模式：产品团队汇总卡「需求数量」格 MUST 为可点击入口（cursor pointer + hover 纯色提亮 + 轻量视觉暗示，再点一次=退出，toggle 语义）；点击弹出门控下拉（搜索框本地过滤 + 限高滚动列表），数据源为 org 响应 `summary.specs`（缺键 MUST 兜底视为空名单、下拉显空态，旧后端/新前端混跑不异常），排序 created 新→旧；全部项目视图条目显示 `project/spec` 消歧、单项目视图只显 spec 名。选中 `(spec_project, spec)` 后全板进入 spec 视图：每张车道卡活动区 MUST 替换为——该车道在当前窗内有此 spec 的 run 时渲染限高滚动轮次列表（复用 `.cmdcenter-lanescroll` 容器样式，每行 `spec名 · 第N轮`，按 started 降序最新在前、`seq` 全史编号由后端下发前端零推导，点击行打开该轮 `RunRecordModal(run_id, spec_project)`，hover 纯色提亮，run_id 缺失禁点兜底保留）；无 run 时渲染灰虚线框「未运行」（REST_BORDER 同族、不可点击）。在飞轮次 MUST 照常入列且可点开。spec-runs 拉取 MUST 走 `useScreenResource` 既有口径（激活+选中时拉取，refreshKey=`project|win|spec`，60s 轮询与序号防乱序随既有 hook）；请求失败保留上轮数据（屏级 Alert 内联提示既有模式），首载未到数据显示与卡片风格同族的「加载中」占位（无动画）。spec 视图下车道卡其余四段（头行/三格指标/sparkline/页脚）MUST 保持实时口径不变。轮次列表 DOM MUST 无 animation/transition（静态渲染红线；antd Popover 开箱动画与全站既有 antd Modal 口径一致、不算违规）。

#### Scenario: 下拉名单与跨项目消歧

- **WHEN** project=''（全部团队）且当前窗名单含 A、B 项目的同名 `fix-x`，用户点「需求数量」并选中 `A/fix-x`
- **THEN** 下拉两条目分别显示 `A/fix-x`、`B/fix-x`；选中后全板 spec 视图数据取自 A 项目 `fix-x`；切到单项目筛选后下拉条目只显 spec 名

#### Scenario: 轮次列表与全史编号

- **WHEN** judge 对 spec-x 全史 10 轮、today 窗内仅 1 轮，用户选中 spec-x
- **THEN** judge 卡活动区限高滚动列表该轮显示 `spec-x · 第10轮`（非「第1轮」）；5 轮全落窗内时顶行为 `第5轮`、底行为 `第1轮`，点击第3轮行打开 RunRecordModal 且 run_id 为第3轮 run

#### Scenario: 未运行与 planner 诚实口径

- **WHEN** ocr 窗内从无 spec-x run、planner 无真实 run 产物
- **THEN** 两卡活动区均显灰虚线框「未运行」、不可点击，planner 不出现派生计数轮次（零伪造红线）

#### Scenario: 在飞轮次可点开

- **WHEN** implementer 正在跑 spec-x（run 在飞、run_id 存在）
- **THEN** 轮次列表含该轮（可点击），点击打开运行记录弹窗；60s 轮询后新产生的轮次自动入列

#### Scenario: 退出与隐式退出

- **WHEN** spec 视图选中 spec-x 时用户再点「需求数量」；或切换 window=today 且 spec-x 非 today 创建
- **THEN** 前者全板回实时模式（活动区恢复 attributables/执行中/待命三分）；后者自动退出 spec 视图；两种退出均同步清除 URL spec 参数

#### Scenario: 深链直达

- **WHEN** URL 携带 `spec=spec-x&spec_project=A` 且 `A/spec-x` 在当前窗名单内，用户直接打开组织总览
- **THEN** 页面直接处于 spec 视图；spec 参数不在名单时清参数回实时模式

#### Scenario: 静态红线

- **WHEN** 渲染 spec 视图轮次列表
- **THEN** 列表 DOM 内无 `animation`、`transition` 属性字样
