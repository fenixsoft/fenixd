# dsh web 账号密码登录

<!-- knowledge: capability=dsh-web-password-login rev=1
     sources=spec/changes/add-dsh-web-password-login -->

fenix-dsh-auth 插件为 dsh web 提供的第二登录通道：未认证访问首页呈现登录页（原生 token-only 401 文本路径在接管面内不生效），账号密码校验通过后以「URL 瞬时带 token」形态完成 dsh 原生会话 cookie 铸造；token URL 登录通道完整保留，凭据可在设置弹窗内配置与移除（回退 token-only）。

## 规则

- **接管面**：宿主半注册三个 exact 路由 `/`、`/auth/login`、`/auth/credentials`；仅此三路径被接管，`/api` 前缀、`/connect`、非 `/` 静态资源（含 ETag/304）与 `/index.html` 直连全部维持原生行为。
- **未认证首页呈现登录页**：GET `/` 无有效会话 cookie 且不满足原生 token 登录条件时返回 200 登录页 HTML（用户名/密码输入、提交按钮、可选错误提示），MUST NOT 出现原生 401 文案「dsh web authentication required; reopen the URL printed by dsh web.」；页面 MUST NOT 含 launchToken、会话 cookie、密码或凭据哈希；静态渲染（禁 CSS animation/transition）；HEAD 只回响应头无 body；错误提示只取服务端白名单 `?error=invalid|locked|unconfigured`，白名单外反射值不落页（转义防 XSS）。
- **未配置引导**：凭据未配置时登录页显示「未配置账号密码」提示，指引先用 token URL 登录后在设置中配置；已配置时仅表单无该提示。
- **token 通道捕获-回放**：GET `/` 携带有效单一 `?token=` 时，插件对上游 `authorizeIndex` 的输出只做「捕获 → 原样回放」（303 + `location: ./` + 铸会话 cookie 的 `set-cookie`），不改变状态码、Location 与 cookie 语义，不自行铸 cookie。已认证分支经 `admit` 取 owner peer 后固定委派 `readResource("/index.html")` 渲染官方 index（webserver 路由无 fall-through，`readResource` 按同一匹配表选 responder——用 `/` 自身会命中插件 handler 得 404）。
- **原生契约不变式**：未认证 `/api/*` 仍 401、`/connect` 仍完成 token 交换后重定向铸 cookie（判据是「与接管前行为一致」，不钉字面状态码——实测 `/connect` 为 302）。
- **登录端点与自动带 token**：`POST /auth/login`（接受 urlencoded 或 JSON）校验通过 303 到同源 `/?token=<launchToken>`——浏览器跟随后由 dsh 原生 `authorizeIndex` 铸 cookie 并 303 回干净 URL，地址栏不残留 token（token 仅瞬时中间态，登录页与 POST 响应均不写入 token）；校验失败统一 303 回 `?error=invalid` 显示「用户名或密码错误」，MUST NOT 区分账号是否存在；凭据未配置 303 回 `?error=unconfigured`；请求体超 8KB 或 Content-Type 白名单外返回 400。`GET /auth/login` 无需认证即返回登录页。
- **同源校验**：登录 POST 与凭据写端点校验 Origin/Host 同源，跨源 403 且不做凭据校验；端口按协议默认值归一化（https 443 / http 80 与省略端口等价），协议不同判跨源；Origin 缺失的非浏览器客户端按同源放行（仍受限流）。反代部署前置条件：代理必须透传 `Host` 头（未透传则合法登录确定性 403）；TLS 终止于反代时须同 scheme 回源（`X-Forwarded-Proto` 不参与判定）。
- **设置「登录」分区**：客户端半在 dsh 官方设置弹窗注册「登录」分区（`settings.section` 槽，官方排序尾）：用户名/密码/确认密码 + 保存 + 「移除账号密码」+ 状态行（已配置用户名/未配置）；保存成功清空密码输入。凭据读写走宿主半 `GET/POST/DELETE /auth/credentials`：`GET` 只回 `{configured, username}`（永不回密码/哈希/盐）；`POST` 校验 username 1–64 字符、password ≥8 且与 confirm 一致否则 400；三端点均要求已认证 owner Peer（未认证 401），POST/DELETE 另校验同源。
- **凭据哈希存储**：凭据存 dsh credentials 记录（key `fenix-dsh-auth/login`，落 `<dsh_home>/.credentials.yaml`，与官方凭据同文件），payload 仅 `version`、`username`、`salt`（16B 随机）、`hash`（scrypt N=16384, r=8, p=1, keylen=64）与参数，MUST NOT 存明文密码。
- **失败限流**：按来源地址（socket remote address）进程内内存计数：60s 窗口内失败 5 次锁 60s，锁定期间即使密码正确也拒（429 或 `?error=locked`，提示「失败次数过多，请 60 秒后重试」）；登录成功清零该来源计数；移除凭据同时清该来源限流；每次尝试顺带清理过期条目防泄漏；进程重启即清零（不持久化）。
- **移除回退**：`DELETE /auth/credentials` 删除凭据记录并回退 token-only，登录页回到未配置提示态、token 通道不受影响；验证收尾同样以此清测试凭据（用户实例不留已知密码）。
- **上游契约失配降级**：apply 阶段探测六项上游契约（`connection.authorizeIndex/authenticatedUrl/admit`、`webServer.register/readResource`、`credentials.modifyRecord`），任一缺失或类型不符即 warn 一次、零路由注册，保持 dsh 原生 token-only 行为；运行期异常捕获降级（原生 401 兜底），MUST NOT 产生未处理异常或进程退出。engines 声明 `>=0.2.0-rc.0 <0.3`，dsh 升级后需复验契约面。

## 关键行为

- 实现与部署在宿主仓 dsh-plugins（跨仓，零构建插件）：插件源码经 `patch -p1` 落地 `/root/dsh-plugins/fenix-dsh-auth/`（六文件）→ profile `/root/.dsh/profiles/web/package.json` 加 `link:` 依赖 + node_modules 建符号链接 + `cordis.patch.yml` insert 行 → `systemctl restart dsh-web` → `/var/log/dsh-web.log` 尾部取新 token URL（token 每次重启轮换，凭据持久保留）。fenixd 侧交付物为 SPEC 目录 `plugin-patch/` 三件套（BASELINE.md / fenix-dsh-auth.patch / DEPLOY.md，跨仓形态见 ADR-339）。
- 客户端半经 `window.__ModuleLoader__.load` 注入设置分区，复用宿主 `@deepseek-ai/dsh-client-ui-primitives` 基元与主题变量，不写全局样式、静态渲染红线与登录页同款。
- 验证门：宿主半纯函数单测以 `node --test 'tests/**/*.test.mjs'` glob 形态执行（node ≥24 对目录 positional 不做测试发现）；部署后按 DEPLOY.md 清单逐项验收（登录页形态、错误/正确密码、`/api` 401 不变式、重启后 token 轮换凭据保留）。

## 代码锚点

主实现与守卫测试在宿主仓 dsh-plugins（跨仓，路径相对 dsh-plugins 仓根）：

- 主实现：`fenix-dsh-auth/index.js`（apply 契约探测与三 exact 路由注册、首页 handler 捕获-回放与登录页渲染、`/auth/login` 登录端点、`/auth/credentials` 凭据端点、scrypt/限流/同源/转义纯函数）、`fenix-dsh-auth/client.js`（设置「登录」分区表单与凭据端点接线）
- 守卫测试：`fenix-dsh-auth/tests/host.test.mjs`（scrypt 哈希与校验、限流窗口与锁定、登录页无凭据无动画、转义白名单、8KB 限读、同源判定）

## 溯源

- 2026-11-10 add-dsh-web-password-login（spec/changes/add-dsh-web-password-login/） — 新建本能力：三 exact 路由接管与登录页替代原生 401 文本、token 通道捕获-回放保留与 `/index.html` 范围声明、登录端点自动带 token 形态、设置「登录」分区与凭据端点契约、scrypt 哈希存储与失败限流、同源校验与反代前置条件、六契约探测 warn-only 降级；2026-11-10 实弹验证 16/16 场景通过（含 `/connect` 行为一致口径实测 302）
