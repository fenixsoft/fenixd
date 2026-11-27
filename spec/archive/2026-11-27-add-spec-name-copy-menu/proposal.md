## Why

SPEC 名称（kebab-case id）是 fenixd 全链寻址键（`/fenix-process <name>`、grep 定位、issue 引用等），用户在 SPEC 列表页浏览时经常需要把某个 SPEC 的名称取出来用于命令与检索；当前列表页没有任何复制入口，用户只能手动进详情、肉眼抄写，易错且低效。在 SPEC 标题上右键即出「复制 SPEC 名称」菜单项，是成本最低的就近取用方式。

## What Changes

- SPEC 列表页（桌面表格）名称列（SPEC 标题：英文名主行 + 中文标题副标题行区域）支持右键：拦截浏览器原生菜单，在鼠标位置弹出上下文菜单，含单项「复制 SPEC 名称」。
- 点击「复制 SPEC 名称」：将该 SPEC 的**英文名**（`record.name`，kebab-case id；不含中文标题）写入用户剪贴板，非阻塞提示复制成功；菜单随即关闭。复制须复用既有 `copyToClipboard` 单源助手（clipboard API 首选 + textarea/execCommand 降级），保证公网 HTTP（非 secure context，frp 隧道访问）下照常可用；写入失败时给出失败提示，不误报成功。
- 菜单交互契约：点击菜单外任意位置、滚动列表或按 Esc 关闭；菜单靠近视口边缘不溢出；菜单操作与弹层经 portal 渲染于行命中面之外，右键与复制操作均不触发行级导航（整行点击进详情既有交互零回归）。
- 范围界定：仅桌面表格名称列接线右键菜单；归档视图行同样可用（复制是只读操作）；移动端卡片流（<768px，触屏无右键语义）本 SPEC 不改动；名称列以外的区域右键保持浏览器原生默认行为。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `dashboard-spec-table`: 名称列新增右键上下文菜单交互——右键 SPEC 标题弹出「复制 SPEC 名称」单项菜单，复制英文名到剪贴板（非安全上下文降级可用），既有整行点击、Why 悬浮、树形展开、过滤排序等交互零回归。

## Impact

- 前端：`core/dashboard/static/src/pages/projects/list.tsx`（名称列单元格接线右键菜单；复用 `src/components/claude-msg/Markdown.tsx` 导出的 `copyToClipboard`，该文件本身零改动）。
- 后端：零改动（纯前端交互，无新端点）。
- 测试：新增 `core/dashboard/static/tests/` node:test 源码扫描测试；生产 rebuild 后浏览器冒烟取证。
- 知识面：知识页 `add-spec-context-menu.md`（v1 右键菜单残留描述）与现行代码不符，随本 SPEC 归档蒸馏一并修正。
