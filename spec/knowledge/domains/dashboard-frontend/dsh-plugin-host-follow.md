<!-- knowledge: capability=dsh-plugin-host-follow rev=1 sources=spec/knowledge/_inbox/done/cordis-runtime-inject-service-gate-for-host-locale-theme.md -->

# dsh 插件宿主 locale/theme 跟随（cordis 服务闸）

fenix 系 dsh 插件（sidebar-tabs / auth / chat-polish / dashboard-bridge / session-advanced-search 等）注入 dsh web 的自绘界面（侧栏菜单条目、功能/工作区切换控件、文件右键菜单、自持 iframe 偏好推送）跟随宿主语言与主题偏好的机制。核心是 cordis 运行时 inject 服务闸形态：可选增强服务禁止静态声明，消费一律走运行时 inject 子上下文。

## 规则

- **服务闸（cordis 客户端插件服务访问铁律）**：插件只能访问自己 inject 声明过的服务——未声明服务的属性访问恒抛 `cannot get property "<服务名>" without inject`。裸 `ctx.locale` 访问 + 轮询的写法每秒抛错→catch→降级，永不成功——「代码在、就是不生效」的根因指纹。
- **静态 inject 声明是激活 fence**：模块导出对象 `inject: [...]` 数组的每一项都是激活前置条件——宿主缺任一项 impl 时插件激活保持 INACTIVE（整个插件死，不是单功能降级；boot 报 waiting for service）。故静态清单只声明宿主 web 必装的硬依赖；locale/theme 这类「想要但不致命」的可选增强服务 MUST NOT 入静态清单，否则在声明项缺席的旧版宿主上跟随降级路径永不触发。
- **运行时 inject 子上下文是可选服务的唯一正解**：apply 内 `ctx.inject(['locale'], (localeCtx) => installLocaleFollow(localeCtx))`（cordis `inject(deps, callback)` = `this.plugin({ inject: deps, apply: callback, name })`）。子 fiber 持自己的声明→服务闸开、回调内属性访问过闸；主插件静态清单不变→fence 约束满足。服务已存在则回调立即执行；late provide 由 cordis 原生 pending→激活处理（微任务级，快于轮询发现路径）；回调返回的函数即 disposer，随父 fiber 卸载级联。TS 侧用结构化断言声明 `inject(deps, callback)` 签名（不引 cordis 内部类型）。
- **manifest 形态不是 client 服务闸**：package.json `dsh.client.inject` 声明对 client 侧服务闸无效——gate 真源是模块导出对象上的 `inject` 属性；manifest 字段无害但不解决问题，不作为声明手段。
- **官方插件先例即规范**：宿主发行包官方插件全部持声明访问——action-cards 静态声明 `["slots","locale","remote"]`，cc-import 同款声明并经 `ctx.inject([...])` 子上下文消费 remote 服务。
- **跟随装配纪律（桥接插件先例）**：跟随安装接入点 MUST 先于固定条目注入与项目同步——挂载点 src 在注册期即拼串取快照缓存（非渲染惰性求值），晚装入首轮面板取到未初始化缓存。装配形态=模块级快照缓存 + `locale/change`/`theme/change` 事件先刷新缓存再广播 + 1s 轮询兜底 late provide（服务闸已开时读取不抛错，重复读幂等）；晚于宿主切换的挂载（右缘页签首开/新面板注册）从缓存取初始注入档，注入档 SHALL 为宿主最近档而非安装时快照。宿主服务缺席/坏值全链降级（缓存 undefined→输出与无跟随现状逐字节一致、不订阅、无报错），降级面收敛在单模块，其它模块不感知能力存在与否。
- **插件自绘文案跟随**：插件注入 dsh web 的纯 DOM 自绘控件文案经插件内词典模块跟随宿主档——宿主档经跟随装配链喂入（初始快照 + 事件实时刷新），值域白名单归一，白名单外忽略维持 last-known-good；无宿主语言服务时降级 zh=既有中文现状，行为零回归。
- **自持 iframe 偏好推送双仓镜像**：桥接插件向自持 iframe（fenixd dashboard embed 页）广播宿主偏好，消息形状 `{kind:'fenix-locale', locale:'zh-CN'|'en-US'}` / `{kind:'fenix-theme', theme}`，kind 字面量与 fenixd 侧通道常量逐字节一致（双仓镜像值纪律，任一侧改动必改另一侧、两侧单测各自钉值）；广播仅发在册窗口（成员资格为唯一发送闸，单窗口抛错跳过并摘除）。fenixd iframe 侧接收规则单源见 locale-i18n / ui-theme 页。
- **多语言页面语言无关判定锚点**：插件与嵌入页面逻辑禁止用中文前缀字符串匹配做状态判定（如 `indexOf('调用 AI')===0` 对 en 档失明）——用 DOM 结构标记（如 `innerHTML.indexOf('streaming-dots')`）作语言无关锚点。

## 代码锚点

fenixd 侧（iframe 通道与宿主档应用，路径相对 fenixd 仓根）：

- iframe 侧语言通道（LOCALE_MESSAGE_KIND 镜像值 + source/origin/kind/值域四层校验）：core/dashboard/static/src/utils/localeChannel.ts
- iframe 侧主题通道（结构先例）：core/dashboard/static/src/utils/themeChannel.ts
- 宿主档应用与优先级短路（applyHostLocale / resolveTarget）：core/dashboard/static/src/utils/localePreference.ts
- 嵌入初始档参数解析（embedLocaleParam）：core/dashboard/static/src/utils/embedMount.ts
- 守卫测试：core/dashboard/static/tests/localeChannel.test.mjs、core/dashboard/static/tests/themeChannel.test.mjs

dsh-plugins 侧（主实现与守卫，跨仓，路径相对 dsh-plugins 仓根）：

- 参考实现（locale/theme 双通道 + 快照白名单归一 + 事件订阅 + 轮询兜底 + dispose 双层收口）：fenix-dsh-session-advanced-search/src/client/hostFollow.ts
- 服务闸接线与静态声明口径（export const inject 硬依赖清单 + apply 内 ctx.inject 子上下文）：fenix-dsh-dashboard-bridge/src/client/index.ts
- 桥接插件跟随装配：fenix-dsh-dashboard-bridge/src/client/localeFollow.ts、fenix-dsh-dashboard-bridge/src/client/themeFollow.ts、fenix-dsh-dashboard-bridge/src/client/pluginLocale.ts
- 守卫测试：fenix-dsh-dashboard-bridge/tests/localeFollow.test.ts、fenix-dsh-session-advanced-search/tests/hostFollow.test.ts

## 溯源

- 2026-11-27 cordis-runtime-inject-service-gate-for-host-locale-theme（spec/knowledge/_inbox/done/cordis-runtime-inject-service-gate-for-host-locale-theme.md） — 折叠：服务闸根因（未声明服务属性访问恒抛）、静态 inject 激活 fence（可选服务禁入静态清单）、运行时 inject 子上下文正解、manifest 形态无效、官方插件声明先例、跟随装配纪律与自持 iframe 双仓镜像推送、语言无关判定锚点
