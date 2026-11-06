# v2 项目详情页六项对齐（白底满宽 + 标题栏收编 + 现产功能对齐）

2026-11-06 用户指令六项（/v2/projects/:name，会话内直接改，未经 SPEC）：

## 生效规则（待蒸馏进 dashboard-frontend 域）

1. **白底满宽变体第三例**：`V2Page` variant 联合增 `"projects"`（类
   `.v2-page.v2-projects`，v2.less 与 `.v2-overview` 同组选择器：页底
   V2_WHITE + `.v2-inner` 去 1400px 收窄、随外部容器满宽、左右固定 30px）；
   `@media` 移动段同组回填 14px 侧距（变体 (0,3,0) 压制 (0,1,0) 移动规则
   的既有陷阱，沿 overview 先例）。
2. **标题收编统一标题栏（v2 第二页）**：projectDetail 弃 V2TitleBand，经
   `V2Page titleBar` 槽位挂 `PageTitleBar`（**挂法①**：渲染在 `.v2-page`
   直下、`.v2-inner` 之前，行壳位满宽贴顶）。声明形态同原版
   projects/list：`back` 回 /v2/overview + `title`=项目名 +
   `subtitle`=「共 N 个 SPEC · M 个活跃」（TitleBarNum 等宽）。
3. **状态下拉值域单源对齐现产**：options 从「表内出现过的状态键派生」改
   `LIST_STATUSES`（listFilters.ts 全 11 态恒显，label 单源 statusMeta）；
   模块级 `STATUS_OPTIONS` 常量。渲染层 antd 256px 虚拟滚动窗口与现产
   行为一致（滚动可见第 11 项「已推送」），非缺陷。
4. **分页参考现产**：`pagination={{ pageSize: 20, showSizeChanger: true,
   showTotal: 共 N 条 }}`（旧 `pagination={false}`）；移动卡片流不分页
   （原型形态维持）。
5. **页签与现产全量对齐**：四页签（后三占位）改六分面——代码审查/测试回归/
   架构蓝图/项目知识/会话接入复用 `pages/projects/components` 现产组件
   （`project` + `active` 门控按需加载），`ListTab` 键域单源 import；
   `PlaceholderPane` 退役。tab 选中态维持内存态（不引入现产 URL `tab`
   参数契约）。

## 协作分工（多会话并行 v2 面，已收口）

- 本页（projectDetail）归 claude 主会话；help.tsx 归 fenixd-61；
  overview/ops 迁移归 fenixd-44；settings/specDetail 由 fenixd-61 接手迁完
  （fenixd-44 确认无主）——六页齐，V2TitleBand/V2BackArrow 已从 shared.tsx
  终删（组件删除，注释保留；守卫测试剥注释不误命中），全量 367 测试 0 失败。
- v2 页挂统一标题栏的挂法以 ① titleBar 槽位为准（fenixd-61 与本会话
  一致；fenixd-44 的 overview/ops 直挂子节点方案待其对齐）。

## 溯源

- 2026-11-06 用户指令六项（未经 SPEC）— core/dashboard/static/src/pages/
  v2/{projectDetail.tsx,shared.tsx,v2.less}；验证：tsc 零错、测试 362/363
  （唯一失败系 fenixd-44 副标题移动端改动的 PageTitleBar 源码守卫，非本页）、
  playwright 8787 实拍（桌面 30px/纯白/顶栏标题/分页 20/页/下拉 11 态/
  六页签现产内容/console 零错误；移动 14px/行壳位/卡片流）、截图
  .history/v2-projects-page2-1106.png。
