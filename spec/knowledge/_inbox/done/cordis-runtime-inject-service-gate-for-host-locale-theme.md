# dsh 插件消费宿主 locale/theme 的服务闸形态（cordis 运行时 inject 子上下文）

## 背景

fenixd 国际化 SPEC（add-framework-i18n-zh-en）落地的「宿主跟随轮」在 dsh web
英文档下失效：fenix 插件（sidebar-tabs/auth/chat-polish/dashboard-bridge）注入
的侧栏菜单与「功能/工作区」切换控件恒中文，而官方插件项（New Session 等）正常。
这些插件早有 localeFollow/themeFollow 实现（读 `ctx.locale`/`ctx.theme` 快照 +
`locale/change`/`theme/change` 订阅 + 1s 轮询兜底 late provide），代码路径看似
完备却从不生效。

## 结论（当前事实）

- **cordis 客户端插件只能访问自己 inject 声明过的服务**：未声明服务的属性访问
  永远抛 `cannot get property "locale" without inject`（cordis `lib/index.js`
  plain trap：fiber 链上找不到 committed impl 即抛）。裸 `ctx.locale` 访问 +
  轮询的写法每秒抛错→catch→降级，永不成功——「代码在、就是不生效」的根因。
- **静态 inject 声明（模块导出对象 `inject: [...]` 数组）是激活 fence**：
  Fiber._refresh() 让插件激活 epoch INACTIVE，直到 inject 每项都有 impl；
  宿主缺该服务时插件**整个**激活 pending（不是该功能降级，是全插件死）。
  故 locale/theme 这类「想要但不致命」的服务禁止静态声明。
- **运行时 inject 子上下文是正解**：apply 内
  `ctx.inject(['locale'], (localeCtx) => installLocaleFollow(localeCtx))`
  （cordis `inject(deps, callback)` = `this.plugin({ inject: deps, apply:
  callback, name })`）。子 fiber 持自己的声明 → 服务闸开、属性访问过闸；
  主插件静态列表不变 → fence 约束满足。服务已存在则回调立即执行；late
  provide 由 cordis 原生 pending→激活处理；回调返回的函数即 apply disposer，
  随父 fiber 卸载级联（与 localeFollow 返回 stop 的现有约定恰好吻合）。
- **package.json `dsh.client.inject`（manifest 形态）不是 client 侧服务闸**：
  真机验证加了 locale 后重载重启仍中文；gate 真源是模块导出对象上的 `inject`
  属性（runner guardedSurface：「the object form's declaration is the
  facade's service gate」）。manifest 字段无害（cc-import 先例）但无效。
- **TS 无缝写法**（结构化断言，避免引 cordis 内部类型）：
  ```ts
  interface ContextWithInject {
    inject(deps: string[], apply: (ctx: unknown) => unknown): { dispose(): void | Promise<void> }
  }
  const stop = (ctx as unknown as ContextWithInject).inject(['locale'], (localeCtx) => { ...; return stopFn })
  ```
  参考实现：`/root/dsh-plugins/fenix-dsh-session-advanced-search/src/client/hostFollow.ts`
  （locale/theme 双通道 + 快照白名单归一 + 事件订阅 + 轮询兜底 + dispose 双层收口）。
- **活证（宿主发行包 0.2.2-rc.1）**：`dsh-client-ui-action-cards/lib/client.js:818`
  `const inject = ["slots","locale","remote"]`；`cc-import` 同款声明并经
  `ctx.inject([...])` 子上下文消费 remote 服务——官方插件全部持声明访问。

## 证据

- 决定性对照：sidebar-tabs 插件对象临时加 `inject: ['locale']` → 重载后
  `ctx.locale` 立即可访问，tab 实时变 Features/Workspaces；还原后复现。
- 探针：sidebar-tabs client.js attempt() 内 console.warn，每秒打
  `ctx.locale threw: cannot get property "locale" without inject`。
- 修复后真机回归（dsh web en 档）：tabs/nav 全英文；设置切中文实时回退。
- 同坑变体（advanced-search 页面在途步骤判定）：中文前缀
  `indexOf('调用 AI')===0` 对 en 档失明——多语言页面里 DOM 结构标记
  （`innerHTML.indexOf('streaming-dots')`）才是语言无关判定锚点。

## 关联

- fenixd 侧 iframe 契约镜像：`core/dashboard/static/src/utils/{localeChannel,themeChannel}.ts`
  （`{kind:'fenix-locale',locale}` / `{kind:'fenix-theme',theme}` postMessage，
  仅认 `ev.source === window.parent`）——dsh 插件向自持 iframe 推送偏好时
  复用同形消息，页面侧 head 早执行 boot script（?theme=/?locale= 参数 →
  父文档属性回退）防首帧错档/白闪。
