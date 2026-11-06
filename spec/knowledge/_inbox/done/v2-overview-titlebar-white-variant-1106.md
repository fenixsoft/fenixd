# v2 六页并入统一标题栏 + 概览白底满宽变体 + 移动密度三则（Dashboard 视图形态变更）

2026-11-06 用户指令（两轮共六项 UI 调整；六页标题栏迁移与帮助页白底由并行
批次同步落地，此处合并登记最终形态）：

## 变更要点

- **v2 六页标题栏豁免整体退役**：`V2Page` 新增 `titleBar` 槽位，六页自画
  `V2TitleBand`（副标题在主标题下方）全部退役，改经 `<V2Page titleBar=
  {<PageTitleBar …/>}>` 声明进全站统一标题栏控件。`titleBar` 渲染在
  `.v2-page` 直下、`.v2-inner` 之前：行壳位（embed/移动端）标题带满宽贴顶
  （sticky 钉视口顶依赖此结构，进 `.v2-inner` 会被居中收窄 + 页顶内边距
  架空——概览页首版子元素挂法实测移动端内缩 14px 即此因）；standalone
  桌面控件本体 null，标题经注册表落 ProLayout 顶栏插槽（副标题基线同行）。
  `unified-page-title-bar` 能力页的 v2 豁免表述与 `V2TitleBand` 残余
  docstring 需随迁清理。
- **概览页白底满宽变体**：`V2Page variant="overview"`（`.v2-page.v2-overview`）：
  页底改白（V2_WHITE），`.v2-inner` 去 1400px 居中收窄、随外部容器满宽、
  左右固定 30px。另有并行批次 `variant="white"`（帮助页）仅改底色。其余页
  缺省灰底 1400px 形态不变。
- **移动断点特异性守卫**：变体选择器 (0,3,0) 会压制媒体查询内 (0,1,0) 的
  移动 `.v2-inner` 侧距规则，`@media` 内已回填变体移动侧距 14px（移动
  原型形态不下探桌面 30px）。
- **标题栏移动档副标题隐藏**：`subtitle` 仅在 `!isMobile` 时渲染（2026-11-06
  用户指令「副标题在移动设备模式中不显示」）——顶栏插槽（HeaderSlot）与
  embed 行壳位两处条件；桌面顶栏与 embed 档（桌面 iframe 语境）不受影响。
  此为全站控件行为，七个常规页移动端同步生效。
- **移动端行壳位退役并入顶栏**：`rowSlot = isEmbedMode()`（原
  `|| isMobile` 档退役，2026-11-06 用户指令「移动端标题栏=最顶那条带
  logo/汉堡的顶栏，内容区不再独立铺标题带」）——standalone 移动端标题经
  注册表走 HeaderSlot 落 ProLayout `ant-pro-global-header`（汉堡+logo+标题
  同条），filters 随 actionsRender 落 `right-content`（help 目录按钮实测
  可用）；顶栏缩进移动档 104→8。48px 移动行壳位形态删除，守卫
  pageTitleBar/embedMount 两 .test.mjs 同步钉新契约。unified-page-title-bar
  能力页「移动端顶栏维持纯品牌」表述需整体改写。
- **移动卡等宽钳制**：KPI 移动网格 `1fr 1fr` → `minmax(0, 1fr)`（钳掉
  隐式 auto 下限）；项目卡 flex 纵列子项加 `min-width: 0`；任务进度磁贴
  移动形态数值/「已完成」改两行（同行 nowrap 撑破磁贴，对齐移动原型
  m-overview overview-kpi-card-progress 形态）。
- **移动简介单行省略**：`ProjectCell` 加 `mobile` 形态参数，简介移动端
  `v2-ellipsis` 单行省略，PC 表格保持 pre-wrap 全显。
- **表格「进入」收编操作菜单**：桌面操作列删「进入」链按钮（列宽 116→72），
  进入/停止/安装托管/删除四项收进三点 Dropdown（进入居首）；行点击跳转
  语义不变。移动卡片菜单维持无进入项（卡片点击即进入）。
- **运行态筛选改胶囊语言**：项目清单 Radio.Group 按钮组退役，改 `.v2-chip`
  胶囊（激活黑底白字 `V2_PRIMARY`，非 antd 描边态——2026-11-06 用户指令）；
  `.v2-chip` 自此跨移动菜单与桌面筛选两处复用。

## 建议折叠去向

- dashboard-frontend/unified-page-title-bar：豁免段改写「v2 六页 2026-11-06
  经 V2Page titleBar 槽位并入，v2 豁免退役」；行壳位段补移动档副标题隐藏。
- dashboard-frontend/v2-commercial-ui：补概览白底满宽变体、titleBar 槽位
  迁移、筛选胶囊与移动等宽钳制。
- dashboard-frontend/v2-overview-page：该页仍描述史前「统计块+卡片网格」
  形态，与 Bento 改版现状脱节，回填批次顺带改写。

## 溯源

- 2026-11-06 用户指令（会话内两轮调整 + 并行批次六页迁移，未经 SPEC）—
  core/dashboard/static src/pages/v2/*、src/components/PageTitleBar.tsx
