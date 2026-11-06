# dsh 面板桥「项目」菜单行折叠开关

<!-- knowledge: capability=dsh-bridge-projects-section rev=2
     sources=spec/knowledge/_inbox/done/bridge-projects-row-toggle-1105.md,spec/knowledge/_inbox/done/antd-table-scroll-maxheight-sticky-th-1106.md -->

dsh-plugins `fenix-dsh-dashboard-bridge` 插件在 dsh web 侧栏注入的「项目」菜单行与内嵌项目分区：菜单行点击是分区的展开/折叠开关，不是主面板切换入口；分区列表 5 行封顶滚动，滚动条与行高对齐宿主原生工作区形态。

## 规则

- **菜单行点击 = 分区展开/折叠开关**：侧栏「项目」菜单行的点击语义是切换内嵌项目分区的展开/折叠态，MUST NOT 触发 `#/projects` 主面板切换——与 `bridge-projects-inline-section` 规范原文一致（「点击分区标题行 SHALL 仅切换展开/折叠态，不切换主面板」）。
- **行右缘状态箭头**：菜单行右缘渲染状态箭头指示折叠态（▸）/展开态（▾，rotate 90° 过渡）；箭头 `pointer-events: none`，点击穿透到拦截层；窄态侧栏不放箭头。
- **整行拦截层机制**：分区展开/折叠由菜单行图标槽（`span.panelGlyph`）内的绝对定位拦截层 span 承载，几何取 `measureHeaderGeometry` 行按钮 rect 相对图标原点的负偏移、盖住整行；React 合成事件 `stopPropagation` 阻断宿主行按钮 `onClick`（selectPanel）。浮层降级路径与 Portal 分区路径双路径同构。
- **拦截层宽度用原始量测**：拦截层宽度取行按钮原始量测值，不钳 360px——侧栏拖宽超 360px 时钳制宽度盖不住整行，行尾点击会穿透为 selectPanel（与浮层分组 `headerWidth` 同口径）。
- **锚点 span overflow 按 portalActive 翻转**：拦截层负偏移越出 16×16 图标盒，锚点 span 的 overflow 在 portalActive 时取 visible / 非激活时取 hidden——恒 hidden 会裁掉拦截层，恒 visible 会让降级窗口的零尺寸占位漏出图标。
- **键盘路径保留主面板注册**：键盘 Enter 触发的合成 click target 是聚焦行按钮本身，子代拦截层不在合成事件路径上，键盘路径仍深链 `#/projects`——`#/projects` 主 keyed 面板 MUST 保留注册（缺席则 selectPanel 抛未注册错误）；鼠标路径被拦截层改道，键盘路径与降级路径行为一致。
- **分区 5 行封顶**：分区列表容器 `maxHeight = min(182px, 46vh)`，182 = `5×34+12`（`GROUP_MAX_HEIGHT`）；行高 34 对齐宿主原生工作区行高；`tests/srcContract.test.ts` 钉 `min(182px, 46vh)` 精确值。
- **分区滚动条定制**：`PROJECT_ROW_CSS` 注入 `[data-testid="fenix-projects-list"]::-webkit-scrollbar-*` 五键规则——宽 6px、thumb 官方变量色（`--dsh-scrollbar-thumb`；`border:0 + background-image:none` 覆全局 thumb 的 border/渐变包装，6px 滑块经不起 2px 边框蚕食）、track 透明、button display:none（去 Chrome 默认上下箭头）。testid 三路径共用（宽态分区/浮层降级/窄态 rail），testid 作用域外滚动条零波及。
- **gutter 预留同值同改**：分区容器 `scrollbar-gutter: stable`，行内容 paddingRight 按定制滑块宽预留 6px，与 PROJECT_ROW_CSS 滚动条规则同值同改（不引用宿主官方 `--dsh-scrollbar-width` 的 10px 口径）。
- **宿主官方 Workspaces 列表同款**：宿主列表类名是 CSS modules 哈希（如 `bhn1Oq_list`），哈希前缀随构建变、`_regionArea`/`_list` 语义段源自源文件类名稳定——选择器 `[class*="_regionArea"] [class*="_list"]` 属性包含匹配；`*="_list"` 会并命中 `_listArea` 外层容器，其 overflow:visible 规则闲置无害，真正滚动列表命中生效。滚动条规则逐键同项目列表款（6px/无箭头/track 透明/官方变量 thumb）。

## 关键行为

插件源码在 dsh-plugins 仓 `fenix-dsh-dashboard-bridge/src/client/panels.tsx`（`renderProjectAnchor` / `renderProjectSection` 折叠门 / `ProjectSectionEntry`）；部署链 = 改源码 → `pnpm build`（tsdown，lib/ 产物经 symlink 即时映射）→ `systemctl restart dsh-web` → `/var/log/dsh-web.log` 尾部取新 token URL 重登。验证配方：插件仓 vitest 全量绿（srcContract 钉高度与滚动条规则形态）+ playwright 命名会话（`-s` 隔离）实拍点击往返；滚动条验证 headless 截图不渲染本体，以规则注入 + 占宽几何为证（offsetWidth−clientWidth=6，overlay 引擎下该 6px 来自 gutter stable 预留）。

## 溯源

- 2026-11-05 bridge-projects-row-toggle-1105（spec/knowledge/_inbox/done/bridge-projects-row-toggle-1105.md） — 新增本能力：菜单行点击定为分区展开/折叠开关（Portal 化交付曾漂移为主面板切换，本条目回归规范意图）、右缘状态箭头、整行拦截层机制约束（宽度不钳 360、overflow 翻转、键盘保留主面板注册）
- 2026-11-06 antd-table-scroll-maxheight-sticky-th-1106（spec/knowledge/_inbox/done/antd-table-scroll-maxheight-sticky-th-1106.md） — 「项目列表固定显示 5 个、超出滚动」需求的本命落地面：分区 7 行改 5 行封顶（GROUP_MAX_HEIGHT=182px、行高 34 对齐原生工作区）、PROJECT_ROW_CSS 滚动条 6px 官方变量款与 gutter 预留同值、宿主官方 Workspaces 列表属性包含选择器同款、部署链 pnpm build→restart dsh-web 与 srcContract 钉值
