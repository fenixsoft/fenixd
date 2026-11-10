# Design: add-dsh-web-password-login

## Context

dsh web（0.2.2-rc.1，安装于 `/usr/lib/node_modules/@deepseek-ai/dsh`）的鉴权由 `@deepseek-ai/dsh-client-connection` 的 `BrowserAuth` 独占：`dsh web` 启动时生成随机 `launchToken` 并打印 `/?token=<launchToken>`，首次访问时 `authorizeIndex` 校验 token → 303 + 签名会话 cookie（`dsh-auth-<sha256(authority)>`，默认 30 天）→ 进入 SPA；cookie 过期后 `authorizeIndex` 走 `writeUnauthorized` 返回纯文本 401。该 401 文本无法定制（上游包），而用户需要一个可自助登录的入口。

dsh 插件有两条可用接缝：① profile `cordis.patch.yml` 的 insert 行可新增插件行（已有 7 个 fenix 插件先例）；② 插件可通过 `webserver.register` 注册自有路由——webserver 匹配序为 exact → 最长 prefix → fallback，而官方 `frontend-static` 只占 fallback 座位，因此插件可安全接管 `/`。认证判定可复用公开 API：`connection.authorizeIndex(indexRequest, indexResponse): boolean`（会写出 303 + cookie 或 401）、`connection.authenticatedUrl(baseUrl): string`、`connection.admit(request): {peer}|{rejection}`、`webServer.readResource(request, peer): Promise<Response>`。

## Goals / Non-Goals

**Goals：**

- 未认证/过期访问 `/` 时呈现登录页而非 401 文本；账号密码校验通过后自动以「URL 带 token」的瞬时形态完成 dsh 原生 cookie 铸造与登录。
- token 登录通道完整保留；`/api`、`/connect`、静态资源语义零改动。
- 账号密码在 dsh web 设置弹窗内可配置、可移除（回退 token-only），密码仅以 scrypt 哈希存储。
- 上游 dsh 升级失配时降级回原生 token-only，不崩不劫持。

**Non-Goals：**

- 不替换/复刻 `connection` 服务行（patch 无法改 name，只能 disabled+insert，需复刻上游 apply 与内部绑定，侵入过大）。
- 不改 dsh 安装包（不覆盖 npm 包）；不改 dsh 前端 SPA。
- 不做多用户/角色/会话管理（仍是单 owner 凭据）；不做找回密码、OAuth、2FA。
- 不接管 `/index.html` 直连（见 D2 范围声明）与 `/api`、`/connect`。
- 不做公网 HTTPS 终端（部署侧责任，DEPLOY.md 提示）。

## Decisions

### D1 交付落点：新建零构建插件 `fenix-dsh-auth`（跨仓），不改 dsh 安装包

用户裁决落仓 fenixd；实现面在 `/root/dsh-plugins/fenix-dsh-auth/`（宿主主树直改），fenixd 侧交付补丁镜像。理由：插件形态可随 dsh 升级保留（不覆盖 npm 包文件）、与既有 7 个 fenix dsh 插件的部署链一致（profile `link:` 依赖 + `cordis.patch.yml` insert 行 + `systemctl restart dsh-web`）。备选：直改 `/usr/lib/node_modules/@deepseek-ai/dsh` 内编译产物——升级即丢、无 git 基线、不可回归，否。

### D2 认证接缝：接管 webserver exact `/` 路由 + 只用公开契约，不替换 connection 服务

`frontend-static` 占 fallback 座位（单座），插件以 `register({kind:"exact", path:"/"})` 抢占 `/` 且不冲突。handler 内用 sink 对象接收 `connection.authorizeIndex` 的输出：返回 false 且写出 303（有效 token 铸 cookie）→ 原样回放 status/headers/body；返回 false 且 401 → 改为返回登录页 HTML（200）；返回 true（cookie 有效）→ `connection.admit(req)` 取 owner peer → `webServer.readResource(new Request("http://dsh.invalid/index.html"), peer)` 委派 fallback 的 `serveStatic` 按 distIndex 渲染官方 index（含 `renderIndex` 注入与 base href）。

关键坑：webserver 的 handler 路由**无 fall-through**，且 `readResource` 按同一匹配表选 responder——若用 `/` 请求自身，会命中插件刚注册的 handler 而返回 404，故认证分支固定用 `/index.html` 取 index。由此 `/index.html` 直连不被接管**范围声明**：dsh web 的用户可见入口（启动打印 URL、登录后跳转、书签）均为 `/`，`/index.html` 保留原生行为（token 有效则正常渲染，过期则原生 401 文本），属本能力明确非范围。备选：disabled+insert 替换 `connection` 行并 fork apply——需复刻 `/api` 前缀桥、`/connect`、index-inject 全局与内部字段访问，侵入过大且随上游漂移，否。

### D3 token 登录原样透传，不自行铸 cookie

有效 `?token=` 的 303 由上游 `authorizeIndex` 产生（含 secret 签名的 `set-cookie`、`location: ./`、`cache-control: no-store`、`referrer-policy: no-referrer`）。插件只做「捕获 → 回放」，不复制签名逻辑，避免 secret 私有不稳定与版本漂移。备选：读取 `authenticatedUrl` 自行拼 302——能工作但丢失 cookie 铸造语义，否。

### D4 「登录后自动在 URL 加 token」= 303 到 `authenticatedUrl(origin + "/")`

密码校验通过后 `303 Location = ctx.connection.authenticatedUrl(<请求 origin + "/">)`，即 `/?token=<launchToken>`；浏览器跟随 → 插件 `/` handler 走 D3 透传 → upstream 303 + cookie → `./` → 应用打开，地址栏不残留 token。该形态完全满足「校验通过后自动在 URL 后加上 token，完成登录」。备选：插件自铸 cookie（需 secret，不可得）→ 否；前端 JS 跳转（登录页无 SPA 环境）→ 否。

### D5 跨仓交付形态与偏离声明（含 DESIGN.md 适用性）

本仓（fenixd）只交付补丁镜像：`plugin-patch/BASELINE.md`（宿主 `/root/dsh-plugins` HEAD、git status、触达文件清单、profile 两配置文件现状摘要、恢复路径）、`plugin-patch/fenix-dsh-auth.patch`（空基线 vs 宿主新插件全量 diff）、`plugin-patch/DEPLOY.md`（部署/回滚人工步骤）。**偏离声明**：实现面在宿主 `/root/dsh-plugins` 主树直改，绝对路径不可进 Deliverables 声明段（等同未声明），以本节与 proposal Impact 记载为准；宿主 profile 配置（`/root/.dsh/profiles/web/package.json`、`cordis.patch.yml`）属宿主运行配置，非本仓交付物，只以 DEPLOY.md 步骤与 BASELINE.md 摘要体现。**DESIGN.md 适用性声明**：本 SPEC 新增界面（登录页、设置「登录」分区）位于 dsh web 宿主侧而非 fenixd dashboard，DESIGN.md（fenixd 界面宪法）的 antd/token 条款不直接适用；登录页仍遵守其静态渲染红线（禁 animation/transition/装饰动效）与克制视觉（复用宿主主题变量/中性色，不引入硬编码品牌色）；设置分区复用宿主 `@deepseek-ai/dsh-client-ui-primitives` 基元，不写全局样式。

### D6 凭据存储：dsh credentials 记录 + scrypt

`credentialKey("fenix-dsh-auth", "login")` 记录，`kind: "grant"`，payload `{version:1, username, salt, hash, N:16384, r:8, p:1, keylen:64}`；写入唯一路径 `ctx.credentials.modifyRecord(key, modifier)`（返回 `undefined` 保持，删除即返回 `undefined`）。理由：复用 dsh 凭据生命周期（文件权限、枚举、事件），密码不以明文进入 settings。备选：dsh settings API（值面向 UI 可回显，有明文/暴露风险）→ 否；插件自管 YAML（绕过凭据服务）→ 否。

### D7 登录页由宿主半直出单文件 HTML

登录页在 SPA 加载前展示，无法依赖客户端 bundle/React；宿主半以内联字符串渲染登录页（无外部资源、无模板引擎），表单 POST 到 `/auth/login`，错误经 `?error=invalid|locked|unconfigured` 服务端渲染。转义所有反射值（错误码白名单 + `escapeHtml`），页面不含 token/凭据。备选：Node 模板文件（多文件但无收益）→ 否。

### D8 失败限流：进程内 Map

`Map<remoteAddress, {fails, windowStart, lockedUntil}>`：60s 窗口内 5 次失败 → 锁 60s；成功清零；每次尝试顺带清理过期条目防泄漏。单进程 web、重启即清零，可接受。备选：持久化限流（重启绕过、复杂度高）→ 否。

### D9 移除账号密码：DELETE 端点 + 清限流

`DELETE /auth/credentials` 删除凭据记录并清空该来源限流状态，回退 token-only；用于用户主动回退与验证收尾清理测试凭据（用户实例不留已知密码）。

## Risks / Trade-offs

- [上游 dsh 升级导致契约漂移] → apply 阶段契约探测 + warn 降级（不注册路由，保持原生 token-only）；测试覆盖缺失分支；升级后需复验（DEPLOY.md 记录检查点）。
- [`restart dsh-web` 打断在飞 GUI 会话] → 部署链沿用既有链路（用户已知情立项）；仅断 web 进程，CLI/daemon 会话不受影响；restart 由实现 Agent 在 daemon 侧执行（不处于 web 进程内）。
- [登录页 XSS/凭据泄漏] → 服务端转义、错误码白名单、页面零 token；登录与凭据写端点同源校验；凭据接口要求 owner Peer。
- [HTTP 明文传输密码] → 仅限内网/本机或 HTTPS 反代场景；DEPLOY.md 明示公网必须 HTTPS 反代。
- [反代部署下 Origin/Host 不同源误拒登录] → 同源判定按协议默认端口归一化（443/80 与省略端口等价），Origin 头缺失按同源放行（仍受限流）；DEPLOY.md 明示反代 MUST 透传 Host 头（如 nginx `proxy_set_header Host $host`），未透传时合法登录将确定性 403。
- [限流内存增长] → 每次尝试清理过期条目；单进程上限可控。
- [/index.html 未接管] → D2 范围声明；用户可见入口均为 `/`；后续如需要可扩展（注册 /index.html 路由并自行渲染 index，需另行决策）。
- [登录后 token 出现在 URL/日志] → token 为瞬时中间态（302 跟随即清除），且 dsh 原生日志语义不变；登录页与 POST 响应不写入 token。

## Migration Plan

1. 在 `/root/dsh-plugins/fenix-dsh-auth/` 落地插件（package.json、index.js、client.js、cordis.patch.yml、README.zh.md、tests/host.test.mjs）。
2. 部署：`/root/.dsh/profiles/web/package.json` 增加 `"fenix-dsh-auth": "link:/root/dsh-plugins/fenix-dsh-auth"`，在 `node_modules` 建同名符号链接（或 `pnpm install`）；`cordis.patch.yml` 增加 `- insert:` 行 `{id: fenix-dsh-auth, name: fenix-dsh-auth}`。
3. `systemctl restart dsh-web` → 从 `/var/log/dsh-web.log` 尾部取新 token URL → 浏览器 token 登录 → 设置弹窗「登录」分区配置账号密码 → 清 cookie 验证登录页与账密登录。
4. 回滚：`DELETE /auth/credentials`（回退 token-only）；彻底卸载 = 删除 profile patch insert 行与依赖 → restart dsh-web。

## Open Questions

无（交付落点、设置入口、双通道行为、失败限流策略、移除能力、执行模式与时机均已与用户确认）。
