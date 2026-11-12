# dsh web 非安全上下文剪贴板写降级

<!-- knowledge: capability=dsh-web-clipboard-fallback rev=1
     sources=spec/knowledge/_inbox/done/dsh-web-http-origin-clipboard-hotfix.md -->

fenix-dsh-clipboard-fallback 外挂插件为 dsh web 在纯 HTTP origin（非 secure context）下补齐剪贴板写入：polyfill `navigator.clipboard.writeText`，让所有裸调剪贴板写入的官方 client 插件在公网 HTTP 访问场景照常工作，且不遮挡原生 API 与上游升级演化。

## 规则

- **问题面按 origin 判定**：经公网纯 HTTP 域名（frp 隧道 home.icyfenix.cn:3080）访问 dsh web 时，浏览器判定非 secure context（`window.isSecureContext === false`），`navigator.clipboard` 整体缺失——这是 Web API 标准行为，非缺陷；127.0.0.1/localhost 属潜在可信 origin，本机访问不复现。dsh 多个 client 插件裸调 `navigator.clipboard.writeText`（open-in-app 右键「复制链接地址」、settings-account 复制登录链接、forge、stats、primitives.writeClipboard 首选路径、session-log-export 降级分支），公网 HTTP 下全部抛 TypeError，菜单/toast 显示「无法复制」。
- **polyfill 只补缺口不覆盖原生**：页面装载早期检测，仅当原生缺失（非 secure context 或宿主未提供）时以 `defineProperty` 定义 `navigator.clipboard = { writeText }`（configurable: true，宿主可覆盖；宿主锁死 navigator 时退化为不安装、保持原生行为），原生已在时不覆盖。`writeText` 以隐藏 textarea + `document.execCommand("copy")`（bind(document)）实现，Promise 语义与原生一致——成功 resolve、失败 reject，调用方既有失败提示分支保持有效。
- **对所有调用方透明**：官方未修的包裸调自动命中 polyfill；官方已改用 primitives.writeClipboard 的路径首选 `navigator.clipboard?.writeText`，同样命中——dsh 升级后无论官方是否统一收编到 writeClipboard，本插件均正确。
- **readText/write 有意不提供**：非 secure context 下读剪贴板（execCommand("paste")）被浏览器禁止、位图无法经 execCommand 降级——保持原生缺失语义，不假装可用。连带效应：session-log-export 的 `supportsDeferredWrite` 因 `write` 缺失自动转走 writeText 降级路径（正好命中 polyfill）；file-actions 复制图片在公网 HTTP 下维持原生失败。paste 类读取不可降级是浏览器安全模型的遗留限制。
- **手势约束**：execCommand("copy") 要求 transient activation（用户手势窗口）——调用方须在菜单项/按钮点击的同步回调链内 await writeText；现有调用方全部满足。
- **安装接线四步（改后必重启）**：源码在 dsh-plugins 仓 `fenix-dsh-clipboard-fallback/`（零构建四件套 package.json / index.js / client.js / cordis.patch.yml）→ profile `/root/.dsh/profiles/web/node_modules/` 建符号链接指向源码目录（无需改 profile package.json/pnpm-lock，先例 fenix-dsh-brand-fenix）→ profile `cordis.patch.yml` 的 insert 列表追加 id/name 两行 → `systemctl restart dsh-web`（插件装载发生在启动时）。
- **交付纪律**：项目级前端修复优先走 fenix 外挂插件（dsh-plugins 仓 + symlink + patch insert），不改 node_modules 产物——直接改 node_modules 属热修，dsh 升级即丢，仅可作临时验证手段。
- **维护面**：插件生命周期独立于 dsh 升级；上游统一改用 writeClipboard 后 polyfill 仍被其首选路径调用，兼容不变；整插件下线 = 删 insert 行 + 删符号链接 + 重启。dsh 主版本跨越（engines `>=0.2.0-rc.0 <0.3` 边界）时复核 loader 契约。

## 关键行为

- **插件 loader 契约红线**：client.js 的 factory 是浏览器侧 cordis 插件构造器，必须返回含 `apply` 方法的对象（本插件 polyfill 在 factory 体内直接执行、apply 空操作；Host 半 index.js 同理保持空 apply——loader 条目按包名装载需要可加载的 cordis 插件）。factory 返回 undefined 会让整个插件批量装载失败：页面报 "Failed to load plugins: invalid plugin, expect function or object with an apply method, received undefined"，**所有插件 client 全挂**，且报错不点名具体插件——排查时先怀疑 insert 列表最后追加的那个。
- **验证判据**：polyfill 状态指纹 = 非 secure context 下 `navigator.clipboard` 为 object、`writeText` 为 function、`readText`/`write` 为 undefined（secure context 下原生保留）；降级路径生效判据 = 捕获 copy 事件且选区内容等于目标文本（execCommand 路径触发 copy 事件，异步 Clipboard API 不会；toast「Copied」只证明调用成功、不区分路径）；SPA 装载确认 = `/plugins/??` 请求清单含 `fenix-dsh-clipboard-fallback/client.js`。端到端验证在公网 HTTP 端点做，127.0.0.1 复现不了问题面。
- **排查配方**：前端 dist 静态 grep 找不到插件代码时，登录后用浏览器网络请求清单（playwright-cli `requests --static`）看真实装载路径，不继续猜路由；playwright `--raw eval` 输出是 JSON 编码字符串，与磁盘文件做字节比较前必须先 json.loads。

## 代码锚点

主实现在宿主仓 dsh-plugins（跨仓，路径相对 dsh-plugins 仓根）：

- 主实现：`fenix-dsh-clipboard-fallback/client.js`（polyfill 全部逻辑：缺口检测、textarea+execCommand writeText、factory 返回 apply）、`fenix-dsh-clipboard-fallback/index.js`（Host 半空 apply 占位）、`fenix-dsh-clipboard-fallback/package.json`（exports 与 engines 声明）、`fenix-dsh-clipboard-fallback/cordis.patch.yml`（loader 清单 insert 定义）
- 消费方：dsh web 各裸调剪贴板写入的 client 插件（open-in-app / settings-account / forge / stats / session-log-export）与 `@deepseek-ai/dsh-client-ui-primitives` writeClipboard；装载接线在 profile `/root/.dsh/profiles/web/cordis.patch.yml`（insert 行）与 `/root/.dsh/profiles/web/node_modules/`（符号链接）
- 守卫测试：无独立守卫测试（验证走 playwright 公网 HTTP 端到端，判据见「关键行为」）

## 溯源

- 2026-11-12 dsh-web-http-origin-clipboard-hotfix（spec/knowledge/_inbox/done/dsh-web-http-origin-clipboard-hotfix.md） — 折叠 dsh web 纯 HTTP origin 剪贴板复制失败排查与外挂修复：问题面按 origin 判定、polyfill 只补缺口不覆盖原生、readText/write 有意不提供与连带降级路径、factory 返回 apply 红线、四步安装接线、交付纪律收敛外挂插件、验证判据与排查配方
