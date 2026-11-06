# 「项目」列表 5 行封顶滚动（dsh 面板桥 + fenixd 侧栏）+ antd sticky 限高实测坑（2026-11-06）

需求：项目列表固定显示 5 个、超出滚动条（对齐 dsh web「工作区」显示逻辑）。
**两处交付面**：

1. **dsh web 侧栏「项目」分区（用户主诉，3080）**——渲染方是 dsh-plugins 仓
   `fenix-dsh-dashboard-bridge` 插件（`~/.dsh/profiles/web/node_modules` link
   直连仓库，lib/ 产物承载）：`src/client/panels.tsx` `GROUP_MAX_HEIGHT`
   7 行→5 行口径（`5×34+12=182px`，min(…, 46vh) 兜底不变），行高 34 =
   原生工作区行高。部署链 = 改源码 → `pnpm build`（tsdown）→
   `systemctl restart dsh-web` → 日志尾部取新 token URL 重登。srcContract
   测试钉 `min(182px, 46vh)` 精确值。首发言行被误读为 fenixd 项目台账表格
   （表格限高方案已全额撤销）。
   **滚动条样式（同日追加指令）**：`PROJECT_ROW_CSS` 注入
   `[data-testid="fenix-projects-list"]::-webkit-scrollbar-*` 规则——宽 6px、
   thumb 官方变量色（border:0 + background-image:none 覆全局 thumb 的
   border/渐变包装，6px 滑块经不起 2px 边框蚕食）、track 透明、button
   display:none（去 Chrome 默认上下箭头）。testid 三路径共用（宽态分区/
   浮层降级/窄态 rail），作用域外滚动条零波及（实测官方 Workspaces 列表
   仍 10px）。inline gutter 预留（paddingRight）同步 6px 同值同改。
   headless 截图不渲染滚动条本体，验证靠占宽几何
   （offsetWidth−clientWidth=6）+ 规则注入。
   **官方 Workspaces 列表同款（同日三段指令）**：宿主列表类名是 CSS modules
   哈希（`bhn1Oq_list`），哈希前缀随构建变、`_regionArea`/`_list` 语义段源自
   源文件类名稳定——选择器 `[class*="_regionArea"] [class*="_list"]` 属性
   包含匹配；`*="_list"` 会并命中 `_listArea` 外层容器（overflow visible
   规则闲置无害，真正的滚动列表 `bhn1Oq_list` 命中生效）。规则逐键同项目
   列表款（6px/无箭头/track 透明/官方变量 thumb）。
2. **fenixd dashboard 独立访问侧栏（8787，embed 模式不渲染故与 3080 无关）**——
   `global.less` `li.ant-menu-submenu > ul.ant-menu-sub.ant-menu-inline
   { max-height: 200px; overflow-y: auto; }`（单项布局占位 40=36+4 行距，
   5 项=200；ProLayout 全站唯一 inline 子菜单锚点）。用户二次指令纠正后落地。

## antd scroll.x 表格限高 sticky 实测坑（撤销方案的留存知识，Chrome 148 / antd 6.6.0 实测）

- 规则在 `global.less`：`li.ant-menu-submenu > ul.ant-menu-sub.ant-menu-inline { max-height: 200px; overflow-y: auto; }`。单项内容 36px、布局占位 40px（含 4px 行距，offsetHeight 不含行距——校准须用 getBoundingClientRect 相对容器实测），5 项完整可见 = 200。
- 锚点依据：ProLayout（app.tsx `menuDataRender`）侧栏是全站唯一 antd inline 子菜单；settings/help 左目录自画不受波及。侧栏折叠态子菜单走浮层 `.ant-menu-vertical` 不命中。展开动画期间 antd 用内联 height+overflow:hidden 驱动，优先级更高，动画结束内联移除后限高生效，互不干扰。
- 守卫：pageChrome.test.mjs 钉选择器与 200px。

## antd scroll.x 表格限高 sticky 实测坑（撤销方案的留存知识，Chrome 148 / antd 6.6.0 实测）

1. **限高层必须在 `.ant-table-content`**：antd `scroll={{ x }}` 给它设 `overflow-x: auto; overflow-y: hidden`，成为 thead 内最近裁剪祖先；限高放业务外层 div 时滚动发生在无 sticky 锚点的层，表头随内容滚走。
2. **sticky 钉 `thead > tr`，不要钉 `th`**：th 的 sticky 约束盒限其行内，computed 显示 sticky/top:0 全对但实测不粘（headTopRel=-164）；钉 tr 实测粘住（trTopRel=0）。白底铺 tr，th 保持 antd transparent 底。
3. **行高校准必须用 rect 相对容器实测**：offsetHeight 不含行距/边距占位（实测 36 vs 40），按 offsetHeight 估 max-height 会截半行。

验证配方：playwright eval 滚动几何（clientHeight/scrollHeight/scrollTop、fullyVisibleItems 按 rect 过滤、末项可达）；headless 截图不渲染滚动条本体，滚动可见性以几何证据为准。
