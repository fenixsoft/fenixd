# dsh client 插件 loader 契约：factory 必须返回含 apply 的插件对象

日期：2026-11-13 ｜ 来源：dsh web 全新会话 boot 故障排查（fenix-dsh-clipboard-fallback）

## 故障

dsh web（127.0.0.1:3080）**全新会话加载必失败**：横幅
`Failed to load plugins / invalid plugin, expect function or object with an "apply" method, received undefined`，
侧栏不渲染。已加载的旧标签页不受影响（boot 只发生在页面装载时）。

## 根因

`window.__ModuleLoader__.load({ id, factory })` 的 **factory 是模块物化函数，loader/cordis
契约要求其返回值必须为含 `apply` 的插件对象**。cordis `Proxy.plugin` 对 undefined 直接抛
invalid plugin；`ClientEntries.create` 的 `Promise.all` 一票否决 → 88 个 entry 全页 boot 失败。

fenix-dsh-clipboard-fallback 的 factory（安全上下文守卫早退分支）**裸 `return`**：

```js
factory(require) {
    if (typeof navigator === 'undefined') return        // ← 返回 undefined！
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') return  // ← 同
    … polyfill 安装 …
    return { apply() {} }                                // 只有这条路径合法
}
```

**环境触发条件（为何作者验证通过而本机挂）**：`http://127.0.0.1` 虽是 HTTP，但浏览器视
localhost/127.0.0.1 为 potentially-trustworthy origin → `isSecureContext === true` →
原生 `navigator.clipboard.writeText` 在位 → 早退分支被命中 → undefined。
经 frp 隧道 `home.icyfenix.cn:3080`（非 localhost 纯 HTTP）时 isSecureContext=false、
原生 clipboard 缺失 → polyfill 路径 → 正常。**任何「环境探测后早退」的写法都会把故障
限定在特定访问入口**，本机全量复现、隧道端全绿，极难定位。

## 修复模式

环境守卫只决定「是否安装 polyfill/是否生效」，**所有路径必须返回插件对象**：

```js
const noop = { apply() {} }
if (typeof navigator === 'undefined') return noop
if (navigator.clipboard && …) return noop
… polyfill …
return { apply() {} }
```

## 排查要点（复用价值）

- 故障栈入口：console `Error: invalid plugin …` ← `ClientEntries.create`
  （`plugins/??@deepseek-ai/dsh-client-modules/client.js` 内 `Promise.all`）。
  **定位具体条目**：`window.__DSH_BOOT__.entries[i]` 与 Promise.all 的 index 对齐
  （index 73 = fenix-dsh-clipboard-fallback）。
- 插件批 bundle（`/plugins/??a/client.js,b/client.js&rev=…`）是 rev 签名的，
  手工改参 fetch 一律 0 字节；只有页面自身发起的 URL 可取。
- esbuild 转译过的插件 load 形态 = `factory: (require) => { var module = {exports:{}} …;
  return module.exports }`；**零构建 raw 透传插件**（`(function(){ 'use strict'
  window.__ModuleLoader__.load({ id: 'x', factory(require){…} }) })()`）没有这层
  module 包装，factory 的返回值即插件本体——raw 插件尤其容易踩本契约。
- 修复插件 client.js 后**无需重启 dsh-web**：服务端逐请求直读磁盘、rev 按内容重算
  （实测批 rev `adb76d6424a3` → `cfdc2a2ad94a`），浏览器整页 reload 即生效。
- 验证三件套：① 全新 open + token URL → 无横幅、`[class*=panelRow]` 8 行、目标入口在；
  ② console 无 invalid plugin；③ 双分支模拟（stub navigator 有/无 clipboard 跑 factory）
  均返回含 apply 对象。
