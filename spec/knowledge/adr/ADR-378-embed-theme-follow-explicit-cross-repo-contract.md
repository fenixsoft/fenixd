# ADR-378：嵌入态主题跟随走双仓显式契约（URL 初始注入 + postMessage 广播），禁同源直读宿主 DOM

date: 2026-11-24
status: accepted

## Context

dashboard 前端具备浅/深双主题后，以 iframe 嵌入 dsh web（`embed=1`）时主题须跟随宿主实时切换。iframe 与宿主同源（同源前缀代理挂载），技术上可以直接读宿主 `body[data-ds-dark-theme]` 属性并用 MutationObserver 监听变化；但该属性是宿主内部 DOM 实现约定而非对外契约，宿主升级（换选择器、换主题机制）会使 iframe 跟随静默失效且无任何报错。宿主侧主题是一等插件 API（`ctx.theme.getTheme()` 快照 + `theme/change` 事件），桥接插件（dsh-plugins 仓独立立项）是宿主与 iframe 之间天然的契约转换层。同仓既有 iframe 集成消息已存在 `fenix-dashboard:*` 命名空间先例（embedBridge `HOST_NEW_SESSION_KIND`）。

## Decision

1. **主题跟随走双仓显式契约，不走同源 DOM 直读**：初始主题经挂载 search 可选参数 `theme=dark|light` 注入（值域白名单，缺省/非法回退独立主题逻辑）；运行期由 host→iframe postMessage 广播 `{kind:'fenix-dashboard:theme', theme:'dark'|'light'}` 实时切换。iframe 侧三层校验（`event.source === window.parent` + `kind` 白名单 + `theme` 值域），不合法消息静默忽略。同源直读宿主 `data-ds-dark-theme` + MutationObserver 被裁定否决：耦合宿主内部 DOM 约定，升级可静默失效。
2. **消息 kind 字面量为双仓冻结契约**：kind 沿用 `fenix-dashboard:*` 命名空间，桥接侧常量字面量与 iframe 侧 `THEME_MESSAGE_KIND` 逐字节一致（双仓镜像值纪律，同 embedBridge 先例）；改字面量或值域须两仓同批改，单仓漂移即静默断链。
3. **嵌入态宿主优先、状态互不污染**：`embed=1` 时宿主档覆盖 localStorage 独立偏好，嵌入态不读取也不写入 `fenix.theme`；嵌入↔独立两形态各自独立解析，配置页主题控件在嵌入态锁定显示「跟随 dsh web」。
4. **职责按仓切分、时序互不阻塞**：iframe 侧行为以「收到合法初始参数/消息即生效」定义，不依赖桥接侧落地时序；宿主侧监听（`ctx.theme.getTheme()` 初始快照转 URL 参数、`theme/change` 事件转 postMessage 广播）由 dsh-plugins 桥接插件独立承担。两仓各自可测、可独立交付。

## Consequences

主题跟随与宿主内部实现解耦：宿主更换主题机制只影响桥接插件一处，iframe 侧零改动；桥接未上线时 iframe 侧行为已定型可测（消息注入即可驱动）。代价：`fenix-dashboard:theme` 的 kind 与值域成为跨仓冻结契约，演进须两仓协调发版；消息通道只承载主题档一枚举值，未来扩载荷（如宿主语言/密度）须走同款显式契约模式另行裁定，不得复用本消息夹带越权语义；postMessage 伪造面由三层校验兜住，非法消息静默忽略不报错。
