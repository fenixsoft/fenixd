# dsh web「项目」菜单行 = 折叠开关（2026-11-05 用户指令交付）

## 结论

dsh-plugins `fenix-dsh-dashboard-bridge` 的「项目」侧栏菜单行点击语义改为**分区展开/折叠开关**，不再切换 `#/projects` 主面板（commit 1268d89；同日 7f3bf22 追加行右缘状态箭头：▸ 折叠 / ▾ 展开 rotate 90° 过渡，pointer-events none 点击穿透到拦截层，窄态不放——lib 构建产物 symlink 即时生效 + dsh-web restart）。

## 根因（实现 vs spec 漂移）

`bridge-projects-inline-section` spec delta 原文即「点击分区标题行 SHALL 仅切换展开/折叠态，不切换主面板」；Portal 化交付时被改成「分区常驻展开（`expanded` 不消费）+ 菜单行点击 = 主面板切换（深链 `#/projects`）」——用户实测点击固定跳转 fenixd 项目页后定调掰回规范意图。

## 机制约束（排障/后续改动须知）

- **整行拦截层机制**：菜单行内图标槽（`span.panelGlyph`）中放绝对定位拦截层 span（几何 = `measureHeaderGeometry` 行按钮 rect 相对图标原点的负偏移），React 合成事件 `stopPropagation` 可阻断宿主行按钮 `onClick`（selectPanel）——浮层降级路径与 Portal 分区路径双路径已生产验证同构。
- **键盘 Enter 不经拦截层**：浏览器对聚焦行按钮合成的 click target = 按钮本身，子代拦截层不在合成事件路径上 → `#/projects` 主 keyed 面板必须**保留注册**（缺席则 selectPanel 抛未注册错误）；鼠标路径被拦截层改道，键盘路径仍深链（残余语义，与降级路径行为一致）。
- **拦截层宽度用原始量测不钳 360**：侧栏拖宽超 360px 时钳制宽度盖不住整行，行尾点击会穿透为 selectPanel（与浮层分组 `headerWidth` 同口径）。
- **锚点 span 的 overflow 需按 portalActive 翻转**（visible/hidden）：拦截层负偏移越出 16×16 图标盒，恒 hidden 会裁掉拦截层；恒 visible 会让降级窗口的零尺寸占位漏出图标。

## 相关

- 插件源码：`/root/dsh-plugins/fenix-dsh-dashboard-bridge/src/client/panels.tsx`（`renderProjectAnchor` / `renderProjectSection` 折叠门 / `ProjectSectionEntry`）
- 验证配方：vitest 77/77 + playwright 命名会话（`-s`）实拍点击往返；鉴权 URL 在 `/var/log/dsh-web.log` 尾部
