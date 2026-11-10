# dsh-web-password-login — dsh web 账号密码登录

## ADDED Requirements

### Requirement: 未认证首页呈现登录页

Host 半 SHALL 接管 dsh web 首页入口路由 `/` 的未认证请求：当请求不携带有效 dsh 会话 cookie、且不满足原生 token 登录条件（GET `/` + 有效单一 `?token=`）时，MUST NOT 返回原生 401 纯文本文案「dsh web authentication required; reopen the URL printed by dsh web.」，而 SHALL 返回 200 登录页 HTML，包含用户名输入、密码输入、提交按钮与可选错误提示。登录页 MUST NOT 包含 launchToken、会话 cookie 值、密码或任何凭据哈希；MUST NOT 使用 CSS 动画或 transition（静态渲染）。HEAD 请求 SHALL 返回响应头且无 body。携带有效会话 cookie 的 `/` 请求 SHALL 返回与 dsh 原生一致的 dsh web 应用首页（含索引注入与 `<base href="./">` 语义）。

#### Scenario: 过期 cookie 打开首页

- **WHEN** 浏览器携带已过期 dsh 会话 cookie 访问 `http://<host>:3080/`
- **THEN** 返回 200 登录页（用户名/密码表单），页面不出现「dsh web authentication required; reopen the URL printed by dsh web.」文案，也不含任何 token 值

#### Scenario: 未配置凭据时访问首页

- **WHEN** 未携带 cookie 访问 `/` 且系统尚未配置账号密码
- **THEN** 返回 200 登录页，并显示「未配置账号密码」提示，指引先用 token URL 登录后到设置中配置

#### Scenario: 已认证首页不受影响

- **WHEN** 浏览器携带有效 dsh 会话 cookie 访问 `/`
- **THEN** 返回 dsh web 应用首页（与插件接管前渲染一致），URL 停留在 `/`

### Requirement: token 登录通道保留

Host 半 SHALL 保留 dsh 原生 token 登录：GET `/` 且携带有效单一 `?token=<launchToken>` 时，MUST 原样透传 dsh 原生响应（303 + `location: ./` + 铸会话 cookie 的 `set-cookie`），不得改变其状态码、Location 与 cookie 语义。`/api` 前缀与 `/connect` 路由的既有鉴权行为 MUST NOT 被改动（未认证 `/api` 仍 401/403，`/connect` 仍完成 token 交换后 303 到 `./api/remote.mux`）。

#### Scenario: token URL 首次登录

- **WHEN** 浏览器访问 `/?token=<当前进程有效 launchToken>`
- **THEN** 收到 303 到 `./` 与 dsh 会话 Set-Cookie，随后应用正常打开

#### Scenario: 未认证 API 仍 401

- **WHEN** 未认证客户端请求 `/api/...`
- **THEN** 返回 401（与原生一致），不返回登录页 HTML

#### Scenario: /connect 行为不变

- **WHEN** 客户端以 `/connect?token=<有效 token>` 完成 token 交换
- **THEN** 行为与插件接管前一致（303 到 `./api/remote.mux` 并铸会话 cookie）

### Requirement: 账号密码登录与自动带 token

Host 半 SHALL 提供登录端点 `POST /auth/login`（接受 `application/x-www-form-urlencoded` 或 JSON），接收用户名与密码：凭据已配置且校验通过时 SHALL 303 重定向到同源 `/?token=<当前 launchToken>`（由 dsh 原生 authorizeIndex 铸 cookie 并 303 回 `./`，URL 上的 token 仅为瞬时中间态）；校验失败时 SHALL 303 回 `/auth/login?error=invalid` 并在登录页显示统一错误（MUST NOT 区分「用户名不存在」与「密码错误」）；凭据未配置时 SHALL 303 回 `/auth/login?error=unconfigured`；请求体超过 8KB 或 Content-Type 不支持时 SHALL 返回 400。登录 POST MUST 校验 Origin/Host 同源，跨源请求 SHALL 返回 403。GET `/auth/login` SHALL 无需认证即可返回登录页。

#### Scenario: 正确密码登录成功

- **WHEN** 在登录页输入已配置的用户名与正确密码并提交
- **THEN** 303 到 `/?token=<launchToken>`，dsh 随即 303 回 `./` 并铸会话 cookie，应用打开且地址栏不残留 token

#### Scenario: 错误密码

- **WHEN** 输入错误密码提交
- **THEN** 303 回 `/auth/login?error=invalid`，登录页显示「用户名或密码错误」，不泄漏账号是否存在

#### Scenario: 跨源提交拒绝

- **WHEN** 以与请求 Host 不同源的 Origin 提交登录表单
- **THEN** 返回 403，不进行凭据校验

### Requirement: 设置分区账号密码配置

Client 半 SHALL 在 dsh web 官方设置弹窗注册「登录」分区（slot `settings.section`，含 `settings.section.icon`），分区内提供用户名、密码、确认密码输入与「保存」按钮，并显示当前配置状态（已配置用户名/未配置）；保存成功后 SHALL 给出成功提示并清空密码输入。设置分区 SHALL 支持「移除账号密码」操作，移除后系统回退为仅 token 登录。凭据读写 SHALL 经宿主半端点 `GET/POST/DELETE /auth/credentials`：`GET` 返回 `{configured, username}`（MUST NOT 返回密码、哈希或盐）；`POST` 要求 username 1-64 字符、password ≥8 字符且与 confirm 一致，否则 400；三个端点均要求已认证 owner Peer，未认证 SHALL 返回 401；POST 与 DELETE MUST 校验 Origin/Host 同源。

#### Scenario: 保存账号密码

- **WHEN** 已登录用户在设置「登录」分区填写用户名与两次一致的密码并保存
- **THEN** 返回成功提示；此后清除 cookie 再访问 `/` 会显示登录页，输入该账号密码可完成登录

#### Scenario: 未认证调用凭据接口

- **WHEN** 未认证客户端请求 `GET /auth/credentials`
- **THEN** 返回 401，不返回任何凭据信息

#### Scenario: 校验失败提示

- **WHEN** 两次密码不一致或密码短于 8 字符时保存
- **THEN** 前端阻止提交或端点返回 400，分区显示错误提示，不写入凭据

#### Scenario: 移除账号密码

- **WHEN** 已配置状态下点击「移除账号密码」并确认
- **THEN** 凭据记录被删除，`GET /auth/credentials` 返回 `{configured:false}`，登录页回到「未配置账号密码」提示状态，token 登录仍可用

### Requirement: 凭据哈希存储与失败限流

凭据 SHALL 存于 dsh credentials 记录（key `fenix-dsh-auth/login`），payload 仅含 `version`、`username`、`salt`（16 字节随机）、`hash`（scrypt N=16384, r=8, p=1, keylen=64）与参数，MUST NOT 存明文密码。登录失败限流 SHALL 按来源地址（socket remote address）内存计数：60 秒窗口内失败 5 次后锁定 60 秒，锁定期间登录 SHALL 返回 429 或 303 到 `/auth/login?error=locked`；登录成功 SHALL 清零该来源计数。

#### Scenario: 失败限流

- **WHEN** 同一来源地址在 60 秒内连续提交错误密码 5 次后再次提交
- **THEN** 请求被拒绝（429 或 `error=locked`），即使密码正确也需等待锁定结束

#### Scenario: 凭据不落明文

- **WHEN** 检查 dsh 本地凭据文件中 `fenix-dsh-auth/login` 记录
- **THEN** 仅见 scrypt 哈希、盐与参数，无明文密码

### Requirement: 上游契约失配降级

Host 半 SHALL 在 apply 阶段探测依赖契约（`ctx.connection.authorizeIndex`、`ctx.connection.authenticatedUrl`、`ctx.connection.admit`、`ctx.webServer.register`、`ctx.webServer.readResource`、`ctx.credentials.modifyRecord`）；任一缺失或类型不符时 MUST NOT 注册替代路由，SHALL 以 `warn` 日志记录一次并保持 dsh 原生 token-only 行为。运行期异常 SHALL 被捕获并降级（记录 warn，返回原生 401 行为），MUST NOT 产生未处理异常或导致进程退出。

#### Scenario: 上游契约缺失

- **WHEN** 在缺少 `authorizeIndex` 的 dsh 版本上启用插件
- **THEN** 启动日志 warn 一次，`/` 保持原生 401 token 行为，无未处理异常

#### Scenario: 运行期异常降级

- **WHEN** 作用域内的读文件/匹配/凭据操作抛出异常
- **THEN** 请求得到降级响应（原生 401 或 500 前的兜底），进程不退出，控制台无未处理异常
