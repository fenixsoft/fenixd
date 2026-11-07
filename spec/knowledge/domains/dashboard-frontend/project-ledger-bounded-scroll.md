# antd 表格限高滚动与 sticky 表头纪律

<!-- knowledge: capability=project-ledger-bounded-scroll rev=2
     sources=spec/knowledge/_inbox/done/antd-table-scroll-maxheight-sticky-th-1106.md -->

antd Table 限高滚动与 sticky 表头的实测实现纪律（Chrome 148 / antd 6.6.0 实测），表格需要限高或粘性表头时直接取用；fenixd 项目台账磁贴（overview/v2）当前不做限高。

## 规则

- **fenixd 项目台账磁贴不限高**：overview 的项目台账表格容器无 max-height 限高、无 sticky 表头，内容自然伸展；规则上禁止对台账表格引入限高/sticky——「项目列表固定显示 5 个、超出滚动」需求的落地面是 dsh web 侧栏「项目」分区（见 dsh-bridge-projects-section），与 fenixd 台账表格无关；镜像限高类 `ov-project-scroll`/`v2-project-scroll` 与对应 pageChrome 守卫断言均不存在，禁回潮。
- **限高层必须在 `.ant-table-content`**：antd `scroll={{ x }}` 给该层设 `overflow-x: auto; overflow-y: hidden`，它既是 thead 内最近的裁剪祖先，也是 sticky 表头的锚点层。限高（max-height + `overflow-y: auto` 覆写）必须写在该层；放在业务侧外层包裹 div 时滚动发生在无 sticky 锚点的层，表头随内容滚走。
- **sticky 钉 `thead > tr`，不钉 `th`**：浏览器把 `th` 的 sticky 约束盒限制在其行（tr）内，无粘附空间——computed style 显示 `position: sticky; top: 0` 全部正确但实测不粘（钉 th 表头相对容器位移 -164px，钉 tr 为 0）。白底铺在 tr 上（th 保持 antd 的 transparent 底），滚动行内容不得从表头下透出。
- **限高数值按真实行高 rect 实测校准**：`offsetHeight` 不含行距/边距占位（实测单项内容 36px、布局占位 40px），按 offsetHeight 估 max-height 会截半行；校准用 `getBoundingClientRect` 相对滚动容器实测。「固定显示约 N 行」取「表头 + 前 N 行实测和」，行高随内容形态浮动，数据形态变化后需重新实测。

## 关键行为

- **滚动验证以几何证据为准**：headless 浏览器默认 hide-scrollbars，截图不渲染滚动条本体，滚动可见性不以截图判断。用 playwright eval 取滚动几何——容器 clientHeight/scrollHeight/scrollTop、完整可见项按 rect 过滤、末行可达性；表头不随内容滚走另以截图核对。

## 溯源

- 2026-11-06 antd-table-scroll-maxheight-sticky-th-1106（spec/knowledge/_inbox/done/antd-table-scroll-maxheight-sticky-th-1106.md） — 新建本页：项目台账磁贴「固定显示约 5 个项目，超出滚动条」落地规则——桌面原型恰 5 条假数据使磁贴封顶视觉印象从未落进实现（缺失行为非回归），限高层钉 .ant-table-content、sticky 钉 thead>tr 非 th、827px 真实行高校准、v2/ov 两域镜像同改与 pageChrome 守卫、几何证据验证配方
- 2026-11-06 antd-table-scroll-maxheight-sticky-th-1106（spec/knowledge/_inbox/done/antd-table-scroll-maxheight-sticky-th-1106.md，17:43 更新版） — 整页覆盖重写：台账磁贴限高方案撤销定案——「5 行封顶」需求落地面改判为 dsh web 侧栏「项目」分区，fenixd 台账磁贴不限高、镜像类与守卫规则废除；antd 限高层/sticky 钉 tr/rect 行高校准实测纪律作为留存知识保留，本页转型为表格限高滚动与 sticky 纪律页
