# Proposal: add-dsh-web-password-login

## Why

dsh web 目前只接受进程启动时打印的 token URL 登录（`/?token=<launchToken>`，launchToken 每进程随机、重启即失效），凭 token 铸出的会话 cookie 默认 30 天过期；cookie 过期或 token 失效后访问首页只会得到纯文本 401 提示「dsh web authentication required; reopen the URL printed by dsh web.」，用户必须到服务器上从终端输出或 `/var/log/dsh-web.log` 重新取 token URL。公网/frp 域名与移动端访问下这一链路尤其不便，也阻碍把 dsh web 交给无服务器权限的使用者。需要为 dsh web 增加第二个登录通道：用户名/密码登录页；token 通道完整保留（双通道）。

## What Changes

- 新建 dsh 插件 `fenix-dsh-auth`（零构建 JS，宿主半 `index.js` + 客户端半 `client.js`），落 `/root/dsh-plugins`，经 fenixd 跨仓 SPEC 交付（本仓交付补丁镜像；用户裁决落仓 fenixd）。
- 宿主半接管 dsh web 首页入口路由 `/`：`?token=` 有效时原样回放 dsh 原生 303（铸 cookie 后进入应用）；cookie 已认证时委派 dsh webServer 渲染官方 index；未认证时不再输出原 401 文案，改为返回 200 登录页 HTML（含用户名/密码表单与错误提示）。
- 新增登录端点 `POST /auth/login`：校验账号密码通过后 303 到同源 `/?token=<launchToken>`（即「URL 自动加上 token」），由 dsh 原生 authorizeIndex 铸会话 cookie 并 303 回干净 URL 完成登录；失败统一回登录页显示「用户名或密码错误」（不区分账号是否存在）。
- 双通道：token URL 登录行为完整保留；未配置账号密码时登录页提示「请先用 token URL 登录，然后在设置中配置账号密码」。
- 设置入口：客户端半在 dsh web 官方设置弹窗注册「登录」分区，可设置用户名/密码（含确认密码）并保存，也支持「移除账号密码」回退为仅 token。
- 凭据存储与安全：凭据经 dsh credentials 服务写入本地凭据文件，仅存 scrypt(N=16384,r=8,p=1,keylen=64) 派生哈希 + 16B 随机盐 + 参数，不落明文；凭据接口要求已认证 owner Peer；登录 POST 校验 Origin/Host 同源；失败限流 5 次/60 秒（按来源地址，进程内内存）。
- 降级：dsh 升级导致上游契约缺失/变化时插件 warn-only 跳过接管，保持 dsh 原生 token-only 行为，不崩、不产生未处理异常。

## Capabilities

### New Capabilities

- `dsh-web-password-login`: dsh web 用户名/密码登录能力——未认证首页呈现登录页（替代 401 文本）、密码校验通过自动带 token 完成登录、token 登录通道保留、未配置凭据提示、设置分区凭据设置/移除、scrypt 哈希存储、同源校验与失败限流、上游契约失配降级。

### Modified Capabilities

（空——已检索 `spec/changes/*/specs/` 与 `spec/archive/*/specs/`，无 dsh web 鉴权/登录相关能力命中；dsh 上游行为不在本仓 capability 全集内，其契约变化由本能力的「上游契约失配降级」Requirement 约束。）

## Impact

- **跨仓实现面**：`/root/dsh-plugins/fenix-dsh-auth/`（新建：`package.json`、`index.js`（宿主半）、`client.js`（客户端半）、`cordis.patch.yml`、`README.zh.md`、`tests/host.test.mjs`）；宿主部署配置 `/root/.dsh/profiles/web/package.json`（加 `link:` 依赖）与 `/root/.dsh/profiles/web/cordis.patch.yml`（insert 行）。
- **上游依赖契约（升级风险）**：`@deepseek-ai/dsh-client-connection` 的 `HostConnectionService.authorizeIndex/authenticatedUrl/admit`、`@deepseek-ai/dsh-host-webserver` 的 `register/readResource`、`@deepseek-ai/dsh-client-ui-settings-general` 的 `settings.section` 槽、`@deepseek-ai/dsh-credentials` 的 `modifyRecord`（含删除语义）；失配时按「上游契约失配降级」Requirement 回到 token-only。
- **部署与验证面**：profile 加 `link:` 依赖 + node_modules 建链 + profile patch insert 行 → `systemctl restart dsh-web` → 从 `/var/log/dsh-web.log` 尾部取新 token URL → playwright 命名会话（-s 隔离）逐 Scenario 实拍（截图落 `/root/fenixd/.history/`），覆盖 token 登录、未认证登录页、错误/正确密码、设置分区保存/移除、`/api` 401 不变；验证收尾以「移除账号密码」清测试凭据。
- **本仓（fenixd）交付物**：`spec/changes/add-dsh-web-password-login/plugin-patch/` 下 `BASELINE.md`、`fenix-dsh-auth.patch`、`DEPLOY.md`；不触 fenixd 运行源码。
- **契约不变项**：`/api` 前缀鉴权（401/403）语义、`/connect` token 交换、非 `/` 静态资源公开访问与 ETag/304、设置弹窗其余官方分区、fenix-dsh-settings-dock 停靠形态。
