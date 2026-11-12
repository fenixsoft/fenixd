# dsh web 纯 HTTP origin 剪贴板复制失败 — 排查与外挂修复记录

日期: 2026-11-12 · 状态: 已修复(fenix 外挂插件 `fenix-dsh-clipboard-fallback`),升级安全

## 症状

在 dsh web 对话中右键外部 http 链接 →「复制链接地址」,toast 提示「无法复制,请检查内容是否可用后重试」。仅发生在经公网纯 HTTP 域名(frp 隧道 `home.icyfenix.cn:3080`)访问时;本机 `127.0.0.1:3080` 不复现。

## 根因(实测确认)

1. 纯 HTTP origin 是非 secure context:`window.isSecureContext === false`,`navigator.clipboard === undefined`(Web API 标准行为,非 bug)。
2. 对话区链接右键走 dsh 自定义 context-menu(`dsh-client-ui-context-menu`),菜单项由 `dsh-client-ui-open-in-app` 注册,「复制链接地址」动作裸调 `navigator.clipboard.writeText(url)` → `TypeError` → 菜单捕获异常显示 `menu.copyFailed` failureLabel。
3. 同类裸调用遍布多个 client 插件包;官方 primitives 已提供带 execCommand 降级的 `writeClipboard` 工具,但只有 `dsh-session-log-export` 用了它。

## 修复方案:外挂插件 polyfill(最终采用)

**插件**: `/root/dsh-plugins/fenix-dsh-clipboard-fallback/`(package.json + index.js + client.js + cordis.patch.yml 四件套,结构照抄 fenix-dsh-brand-fenix)。

**机制**: client.js 在页面装载早期 polyfill `navigator.clipboard`——仅当原生缺失(非 secure context)时,定义 `{ writeText }`(隐藏 textarea + `document.execCommand("copy")`,Promise 语义与原生一致:成功 resolve、失败 reject,调用方失败提示分支保持有效)。**对所有裸调用方透明**:

- 官方未修的包(open-in-app/settings-account/forge/stats)裸调自动命中 polyfill;
- 官方已修的路径(primitives.writeClipboard 首选 `navigator.clipboard?.writeText`)同样命中;
- `readText`/`write` 有意不提供:非 secure 下无法降级(浏览器禁止 execCommand paste、位图无法经 execCommand 复制),保持原生缺失语义;session-log-export 的 `supportsDeferredWrite` 因 `write` 缺失自动转走 writeText 降级,正好命中 polyfill。

**安装接线**(dsh 0.2.2-rc.1):

1. 插件源码 `/root/dsh-plugins/fenix-dsh-clipboard-fallback/`;
2. 符号链接 `~/.dsh/profiles/web/node_modules/fenix-dsh-clipboard-fallback -> /root/dsh-plugins/fenix-dsh-clipboard-fallback`(先例:fenix-dsh-brand-fenix;无需改 profile package.json/pnpm-lock);
3. `~/.dsh/profiles/web/cordis.patch.yml` 的 insert 列表追加 `- id/name: fenix-dsh-clipboard-fallback`;
4. `systemctl restart dsh-web`(插件装载在启动时,须重启)。

**关键坑**(踩过一次): client.js 的 `factory` 是浏览器侧 cordis 插件构造器,**必须返回含 `apply` 方法的对象**(先例插件的 factory 尾部都 `return { apply(ctx) {...} }`)。返回 undefined 会让整个插件批量装载失败,页面报 "Failed to load plugins: invalid plugin, expect function or object with an apply method, received undefined",**所有插件 client 全挂**。polyfill 放 factory 体内直接执行,`apply` 保持空操作。

## 曾采用又回滚的方案(留档)

第一版直接改了 4 个 node_modules 包的 `lib/client.js`(open-in-app/settings-account/forge/stats,换 primitives.writeClipboard),已验证有效,但属热修——dsh 升级即丢。已全部从备份(`/root/fenixd/.history/*.client.js.bak-20261112`)回滚,修复收敛到外挂插件。

## 验证(playwright 在 http://home.icyfenix.cn:3080 端到端)

- polyfill 状态:非 secure context 下 `navigator.clipboard` 为 object、`writeText` 为 function、`readText`/`write` 为 undefined(符合设计);
- 网络确认:`/plugins/??...fenix-dsh-clipboard-fallback/client.js` 被 SPA 装载;
- 行为:右键链接 → 复制 → toast「Copied」;copy 事件捕获选区内容 = 链接 URL(execCommand 降级路径触发 copy 事件,异步 Clipboard API 不会,事件捕获同时证明降级路径生效);
- 修复前基线:同场景 toast「Could not copy」(已复现)。

## 维护注意

- 插件在 `/root/dsh-plugins/`,dsh 升级不受影响;若上游官方包日后统一改用 primitives.writeClipboard,polyfill 依然兼容(被其首选路径调用),可保留;也可整插件下线(删 insert 行 + 链接 + 重启)。
- dsh 主版本跨越(engines `>=0.2.0-rc.0 <0.3`)时注意 loader 契约是否变化(factory 须返回含 apply 对象这一坑可能在升级后复检)。
- 浏览器侧遗留限制:非 secure context 下 Clipboard **读取**(paste 类)无法降级,属浏览器安全模型约束。

## 教训

- 前端 dist 静态 grep 找不到插件代码时,应登录后用浏览器网络请求(`playwright-cli requests --static`)看真实装载路径,而不是继续猜路由。
- playwright `--raw eval` 输出是 JSON 编码字符串,与磁盘文件做字节比较前必须先 json.loads,否则会误判文件不同。
- fenix 插件 client.js 的 factory 必须返回 `{ apply }` 插件对象;漏返会拖垮**全部**插件 client 的批量装载,报错文案只说 "invalid plugin",不点名是哪个插件——排查时先怀疑最后 insert 的那个。
- 项目级修复优先走 fenix 外挂插件(/root/dsh-plugins + symlink + patch insert),不改 node_modules 产物;后者仅作临时热修。
