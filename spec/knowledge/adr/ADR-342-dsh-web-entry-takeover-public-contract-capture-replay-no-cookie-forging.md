# ADR-342：dsh web 入口接管走公开契约捕获-回放，不替换 connection 服务、不自行铸 cookie

date: 2026-11-10
status: accepted

## Context

dsh web 原生鉴权由 connection 服务的 BrowserAuth 独占：launchToken 每进程随机，会话 cookie 由上游 secret 签名铸造（secret 私有且随版本不稳定），未认证首页的 401 纯文本不可定制。要为 dsh web 增加账号密码登录通道，须在不动 dsh 安装包（npm 产物，升级即丢、无 git 基线）的前提下接管入口路由。可选接缝两条：① disabled+insert 替换 `connection` 服务行并 fork 其 apply——需复刻 `/api` 前缀桥、`/connect`、index-inject 全局与内部字段访问，侵入过大且随上游漂移；② 只用公开契约，在 webserver 上抢占 exact `/` 座位（官方 `frontend-static` 仅占 fallback 座位，exact 无冲突），捕获-回放上游 `authorizeIndex` 输出。

## Decision

dsh web 入口类插件只使用上游公开契约：`webServer.register`（exact 路由）+ `connection.authorizeIndex/authenticatedUrl/admit` + `webServer.readResource` + `credentials.modifyRecord`。有效 token 的 303（含签名 `set-cookie`）由上游产生，插件只做「捕获 → 原样回放」，不读取 secret、不复制签名逻辑、不自行铸 cookie；已认证分支经 `admit` 取 peer 后固定委派 `readResource("/index.html")` 渲染官方 index（webserver 路由无 fall-through，`readResource` 按同一匹配表选 responder——用 `/` 自身会命中插件 handler 得 404）。不替换 `connection` 服务行。

## Consequences

- 插件不携带上游内部复刻面，dsh 升级的失配面收敛为 apply 阶段的公开契约探测（六项方法存在性与类型），失配 warn-only 零注册、降级回原生 token-only。
- `/index.html` 直连不被接管（保留原生 token 渲染/401 行为）——这是本裁定无 fall-through 语义的直接产物，用户可见入口均为 `/`；扩展接管 `/index.html` 须另行决策（需自行渲染 index）。
- 登录成功形态被约束为「303 到 `authenticatedUrl` 产出的 `/?token=` 瞬时中间态」，由上游铸 cookie——插件无法绕过该形态直接建立会话。
- apply 契约探测成为入口类插件的装配前置纪律：契约不齐即零注册，路由接管永不半生效。
