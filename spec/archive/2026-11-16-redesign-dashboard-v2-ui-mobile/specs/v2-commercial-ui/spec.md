# v2-commercial-ui Specification（移动端适配）

## MODIFIED Requirements

### Requirement: v2 六页移动端布局形态（<768px 断点）

界面原型（UI 真相源·移动形态）：`spec/changes/redesign-dashboard-v2-ui-mobile/prototype/`（m-overview.html、m-project-detail.html、m-spec-detail.html、m-settings.html、m-help.html、m-ops.html；渲染凭证 screenshots/*.png）。移动形态布局与组件形态 **界面以 prototype/ 为准**，冲突升级用户裁决；桌面形态仍以 redesign-dashboard-v2-ui prototype/ 为准。

- 概览：KPI 2×2 磁贴、告警单条摘要 + 双按钮、项目台账转堆叠项目卡
- 项目详情：筛选双下拉、SPEC 表格转卡片流（名称+状态/模式/验证胶囊+阶段进度+耗时）、无新建按钮
- SPEC 详情：标题行换行收纳、无状态转移按钮、项目信息单列键值行、页签短标签
- 配置：左菜单转横向滑动胶囊（ACTIVE 黑底）、Provider 堆叠卡、开关行
- 帮助：目录抽屉化（Drawer）、无搜索入口、正文单列
- 运维：统计 chips、告警堆叠卡（裁决 Select 全宽、双按钮行）

#### Scenario: 断点切换形态

- **WHEN** 视口 <768px 渲染任一 v2 页面
- **THEN** 呈现移动形态（以 prototype/ 为准）；≥768px 呈现桌面形态（以 redesign-dashboard-v2-ui prototype/ 为准），两形态零交叉污染

#### Scenario: 移动端越界与触控

- **WHEN** 390px 视口渲染六页
- **THEN** 无横向滚动越界（body scrollWidth ≤ 视口宽）；操作按钮/入口触控目标可用（≥28px 控件 + 命中区 ≥32px，可复用 global.less 移动端作用域 `.touch-expand` 工具类，对齐仓库触控目标约定）

#### Scenario: 移动端信息密度

- **WHEN** 长文本（≥200 字注释/告警明细）在移动形态渲染
- **THEN** 换行完整呈现（pre-wrap），MUST NOT 截断伪装；数值口径缺口显示「—」

#### Scenario: 依赖前序 SPEC

- **WHEN** 本 SPEC 派发
- **THEN** depends_on redesign-dashboard-v2-ui（v2 页面族与主题单源已合入 main），本 SPEC 仅增量修改其产物
