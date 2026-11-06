# 项目台账磁贴限高滚动与 sticky 表头

<!-- knowledge: capability=project-ledger-bounded-scroll rev=1
     sources=spec/knowledge/_inbox/done/antd-table-scroll-maxheight-sticky-th-1106.md -->

概览与 v2 项目台账磁贴的桌面形态高度口径：台账表格固定显示约 5 个项目、超出滚动查看、表头 sticky 钉住不随内容滚走；承载 antd Table 限高滚动与 sticky 表头的实现纪律、两域镜像守卫与验证配方。

## 规则

- **高度口径**：桌面形态（≥768px）项目台账磁贴内表格封顶显示约 5 个项目，超出部分容器内滚动；移动形态项目台账转堆叠项目卡，不限高。
- **限高层必须在 `.ant-table-content`**：antd `scroll={{ x }}` 给 `.ant-table-content` 设 `overflow-x: auto; overflow-y: hidden`，该层是 thead 内最近的裁剪祖先，也是 sticky 表头的锚点层。限高（max-height + `overflow-y: auto` 覆写）必须写在该层；放在业务侧外层包裹 div 时滚动发生在无 sticky 锚点的层，表头随内容滚走。
- **sticky 钉 `thead > tr`，不钉 `th`**：浏览器把 `th` 的 sticky 约束盒限制在其行（tr）内，无粘附空间——computed style 显示 `position: sticky; top: 0` 全部正确但实测不粘。白底铺在 tr 上（th 保持 antd 的 transparent 底），滚动行内容不得从表头下透出。
- **限高数值按真实行高校准**：行高随简介换行/状态胶囊行数浮动，「固定显示约 5 个」取「表头 + 前 5 行 offsetHeight」实测和（当前 827px = 表头 47 + 前 5 行 780）；近似口径无法精确保证恰好 5 行，数据形态变化后需按行 offsetHeight 重新实测校准。
- **两域镜像，跨域禁互引**：v2 侧 `.v2-project-scroll`（`pages/v2/v2.less`）与现产 overview 侧 `.ov-project-scroll`（`global.less`）各自定义同一规则，限高数值两处同改一致；`tests/pageChrome.test.mjs` 守卫钉两域 class 接线、限高规则存在、镜像同值与 sticky-on-tr 形态。
- **消费接线**：现产 overview `ProjectTable.tsx` 桌面表格容器挂 `ov-bento-table ov-project-scroll`；v2 `overview.tsx` ProjectPanel 表格容器挂 `v2-bento-table v2-project-scroll`。改容器类名或接线必须同步守卫断言。

## 关键行为

- **滚动验证以几何证据为准**：headless 浏览器默认 hide-scrollbars，截图不渲染滚动条本体，滚动条可见性不以截图判断。用 playwright eval 取滚动几何——容器 clientHeight/scrollHeight/scrollTop、thead tr 相对滚动层 rect top（钉住态为 0）、末行可达性；表头不随内容滚走另以截图核对。

## 溯源

- 2026-11-06 antd-table-scroll-maxheight-sticky-th-1106（spec/knowledge/_inbox/done/antd-table-scroll-maxheight-sticky-th-1106.md） — 新建本页：项目台账磁贴「固定显示约 5 个项目，超出滚动条」落地规则——桌面原型恰 5 条假数据使磁贴封顶视觉印象从未落进实现（缺失行为非回归），限高层钉 .ant-table-content、sticky 钉 thead>tr 非 th、827px 真实行高校准、v2/ov 两域镜像同改与 pageChrome 守卫、几何证据验证配方
