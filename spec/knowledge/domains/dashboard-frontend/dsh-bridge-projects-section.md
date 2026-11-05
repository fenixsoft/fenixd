# dsh 面板桥「项目」菜单行折叠开关

<!-- knowledge: capability=dsh-bridge-projects-section rev=1
     sources=spec/knowledge/_inbox/done/bridge-projects-row-toggle-1105.md -->

dsh-plugins `fenix-dsh-dashboard-bridge` 插件在 dsh web 侧栏注入的「项目」菜单行与内嵌项目分区：菜单行点击是分区的展开/折叠开关，不是主面板切换入口。

## 规则

- **菜单行点击 = 分区展开/折叠开关**：侧栏「项目」菜单行的点击语义是切换内嵌项目分区的展开/折叠态，MUST NOT 触发 `#/projects` 主面板切换——与 `bridge-projects-inline-section` 规范原文一致（「点击分区标题行 SHALL 仅切换展开/折叠态，不切换主面板」）。
- **行右缘状态箭头**：菜单行右缘渲染状态箭头指示折叠态（▸）/展开态（▾，rotate 90° 过渡）；箭头 `pointer-events: none`，点击穿透到拦截层；窄态侧栏不放箭头。
- **整行拦截层机制**：分区展开/折叠由菜单行图标槽（`span.panelGlyph`）内的绝对定位拦截层 span 承载，几何取 `measureHeaderGeometry` 行按钮 rect 相对图标原点的负偏移、盖住整行；React 合成事件 `stopPropagation` 阻断宿主行按钮 `onClick`（selectPanel）。浮层降级路径与 Portal 分区路径双路径同构。
- **拦截层宽度用原始量测**：拦截层宽度取行按钮原始量测值，不钳 360px——侧栏拖宽超 360px 时钳制宽度盖不住整行，行尾点击会穿透为 selectPanel（与浮层分组 `headerWidth` 同口径）。
- **锚点 span overflow 按 portalActive 翻转**：拦截层负偏移越出 16×16 图标盒，锚点 span 的 overflow 在 portalActive 时取 visible / 非激活时取 hidden——恒 hidden 会裁掉拦截层，恒 visible 会让降级窗口的零尺寸占位漏出图标。
- **键盘路径保留主面板注册**：键盘 Enter 触发的合成 click target 是聚焦行按钮本身，子代拦截层不在合成事件路径上，键盘路径仍深链 `#/projects`——`#/projects` 主 keyed 面板 MUST 保留注册（缺席则 selectPanel 抛未注册错误）；鼠标路径被拦截层改道，键盘路径与降级路径行为一致。

## 关键行为

插件源码在 dsh-plugins 仓 `fenix-dsh-dashboard-bridge/src/client/panels.tsx`（`renderProjectAnchor` / `renderProjectSection` 折叠门 / `ProjectSectionEntry`）；交付链路为 lib 构建产物 symlink 即时生效 + dsh-web restart。验证配方：插件仓 vitest 全量绿 + playwright 命名会话（`-s` 隔离）实拍点击往返，dsh-web 鉴权 URL 取 `/var/log/dsh-web.log` 尾部。

## 溯源

- 2026-11-05 bridge-projects-row-toggle-1105（spec/knowledge/_inbox/done/bridge-projects-row-toggle-1105.md） — 新增本能力：菜单行点击定为分区展开/折叠开关（Portal 化交付曾漂移为主面板切换，本条目回归规范意图）、右缘状态箭头、整行拦截层机制约束（宽度不钳 360、overflow 翻转、键盘保留主面板注册）
