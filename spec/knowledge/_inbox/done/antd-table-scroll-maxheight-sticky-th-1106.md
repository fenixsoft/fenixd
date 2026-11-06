# antd Table 限高滚动 sticky 表头三坑（overview/v2 项目台账磁贴，2026-11-06）

需求：dsh web 项目台账磁贴「固定显示约 5 个项目，超出滚动条」。根因是**行为从未实现**：桌面原型（variant-b-bento.html）恰好只有 5 条假数据，磁贴高度封顶的视觉印象从未落进实现——真实 6 个项目时表格无限撑高。属缺失行为非回归。

## 三坑（Chrome 148 实测，antd 6.6.0）

1. **限高层必须在 `.ant-table-content`，不能放业务侧包裹 div**。antd `scroll={{ x }}` 给 `.ant-table-content` 设 `overflow-x: auto; overflow-y: hidden`，它成为 thead 内最近的裁剪祖先；限高放在外层 div 时滚动发生在无 sticky 锚点的层，表头随内容滚走。
2. **sticky 钉 `thead > tr`，不要钉 `th`**。浏览器对 `th` 的 sticky 约束盒限制在其行（tr）内，无粘附空间——computed style 显示 position:sticky/top:0 全部正确但实测不粘（headTopRel=-164）；改钉 tr 实测粘住（trTopRel=0）。白底铺 tr 上（th 保持 antd 的 transparent 底）遮滚过行。
3. **数值按真实行高校准，静态值无普解**。行高依简介换行/状态胶囊行数浮动（实测本机 6 行 [184,124,124,184,164,164] + 表头 47），「固定显示 5 个」取 `表头 + 前 5 行 offsetHeight` 实测和（827px），数据形态变化后需再校准。近似口径无法精确保证恰好 5 行。

## 交付形态

- 两域镜像（跨域禁互引）：v2 侧 `.v2-project-scroll`（v2.less）、overview 侧 `.ov-project-scroll`（global.less），数值 827 同改，pageChrome.test.mjs 守卫钉接线 + 两域值一致 + sticky-on-tr 形态。
- max-height 写在 `.ant-table-content`；overflow-y: auto 覆写 antd 的 hidden。
- 验证配方：playwright eval 滚动几何（clientHeight/scrollHeight/scrollTop、thead tr rect 相对滚动层 top、末行可达），headless 截图不渲染滚动条本体（headless 默认 hide-scrollbars），滚动条可见性以几何证据为准。

消费方：overview/components/ProjectTable.tsx（桌面表格容器 `.ov-bento-table ov-project-scroll`）、v2/overview.tsx ProjectPanel（`.v2-bento-table v2-project-scroll`）。移动形态堆叠卡不限高。
