## Deliverables

```yaml
- path: spec/changes/add-dsh-web-password-login/plugin-patch/BASELINE.md
  kind: new
- path: spec/changes/add-dsh-web-password-login/plugin-patch/fenix-dsh-auth.patch
  kind: new
- path: spec/changes/add-dsh-web-password-login/plugin-patch/DEPLOY.md
  kind: new
```

> 跨仓交付形态见 design.md D5/D5 偏离声明：实现面在 `/root/dsh-plugins/fenix-dsh-auth/` 宿主主树直改（新建零构建插件），部署配置在 `/root/.dsh/profiles/web/{package.json,cordis.patch.yml}`；本仓交付物为基线快照 + 补丁镜像 + 部署文档。宿主触达文件为 `/root/dsh-plugins/fenix-dsh-auth/` 下 package.json、index.js、client.js、cordis.patch.yml、README.zh.md、tests/host.test.mjs 与 profile 两个配置文件——绝对路径不可进声明段（等同未声明），故以本段注记与 design.md/proposal.md Impact 记载为准。

## 1. 基线快照（跨仓只读，最先执行）

- [ ] 1.1 记录宿主基线：`git -C /root/dsh-plugins rev-parse HEAD` 与 `git -C /root/dsh-plugins status --porcelain` 原样写入 `plugin-patch/BASELINE.md`，确认 `/root/dsh-plugins/fenix-dsh-auth/` 尚不存在、清单中无同名插件
- [ ] 1.2 只读记录部署面现状摘要入 `BASELINE.md`：`/root/.dsh/profiles/web/package.json` 的 dependencies 键集合与 `dsh.profile.bundles` 是否含 fenix-dsh-auth、`/root/.dsh/profiles/web/cordis.patch.yml` 的 insert 行清单与行号，并抄录当前 dsh 版本（`node /usr/bin/dsh --version`）

## 2. 宿主半实现（宿主主树直改，新建插件）

- [ ] 2.1 创建 `/root/dsh-plugins/fenix-dsh-auth/package.json`（type module；exports ".": "./index.js"、"./client": "./client.js"；engines.dsh ">=0.2.0-rc.0 <0.3"；dsh.bundle.patch "./cordis.patch.yml"；dsh.client {platform:"web", inject:["@deepseek-ai/dsh-client-ui-settings-general"]}）、`cordis.patch.yml`（`- insert: - id: fenix-dsh-auth` + `name: fenix-dsh-auth`）、`README.zh.md`（能力、部署、安全边界、回滚）
- [ ] 2.2 `index.js` 的 `apply(ctx)`：按 design.md「上游契约失配降级」Requirement 探测 `ctx.connection.authorizeIndex/authenticatedUrl/admit`、`ctx.webServer.register/readResource`、`ctx.credentials.modifyRecord`，缺失或不匹配时 `ctx.logger?.warn?.('[fenix-dsh-auth] ...')` 记录一次并直接 return（不注册任何路由）
- [ ] 2.3 `index.js` 注册 exact `/` handler：sink 捕获 `authorizeIndex({headers,method,url}, sink)`；非 401 且写出 303 → 原样回放 status/headers/body；401 → 200 登录页 HTML（`?error=` 提示、未配置凭据提示）；返回 true → `admit(req)` 取 owner peer，`readResource(new Request("http://dsh.invalid/index.html"), peer)` 回写 index 响应；HEAD 只写头；全程 try/catch 降级
- [ ] 2.4 `index.js` 注册 exact `/auth/login`：GET 返回登录页；POST 解析 urlencoded/JSON（body ≤8KB、Content-Type 白名单）、Origin/Host 同源校验（跨源 403）、限流判定、scrypt 校验；成功 303 到 `authenticatedUrl(请求 origin + "/")`，失败 303 到 `/auth/login?error=invalid|unconfigured|locked`
- [ ] 2.5 `index.js` 注册 exact `/auth/credentials`：GET 返回 `{configured, username}`；POST（`admit` owner 校验、username 1-64、password ≥8 且与 confirm 一致、scrypt 生成、`modifyRecord` 写入）；DELETE（删除记录 + 清该来源限流）；未认证 401，参数非法 400
- [ ] 2.6 从 `index.js` 导出纯函数供测试：`hashPassword/verifyPassword`（scrypt）、`rateLimitHit`、`renderLoginPage`（转义）、`parseLoginBody`、`isSameOrigin`

## 3. 客户端半实现（设置分区）

- [ ] 3.1 `client.js`：`window.__ModuleLoader__.load({id:"fenix-dsh-auth", factory(require){...}})` 内 `apply(ctx)`，以 `ctx.slots.inject("settings.section", () => ctx.slots.register({name:"settings.section", id:"fenix-auth", order:<官方排序尾>, label:()=>"登录"}, Section))` 注册分区，并注册 `settings.section.icon`
- [ ] 3.2 `client.js`：分区表单（用户名/密码/确认密码/保存/移除账号密码/状态行），挂载时 `GET /auth/credentials` 回填用户名与状态，保存走 `POST`、移除走 `DELETE`，成功/失败提示（含 401 未登录、400 校验失败的提示）
- [ ] 3.3 `client.js` 视觉约束：复用宿主 `@deepseek-ai/dsh-client-ui-primitives` 基元与宿主主题变量，无 animation/transition，不写全局样式、不覆盖其它分区

## 4. 单测

- [ ] 4.1 `tests/host.test.mjs`（node:test）：scrypt 哈希/校验正确与错误、限流 5 次/60s 触发与窗口过期、登录页 HTML 不含 token/密码且转义 `<script>`、body 解析超长拒绝、同源判定（同源/跨源/缺失 Origin）
- [ ] 4.2 `node --test /root/dsh-plugins/fenix-dsh-auth/tests/` 全绿

## 5. 部署与实拍验证（部署链沿用既有）

- [ ] 5.1 部署：`/root/.dsh/profiles/web/package.json` 增加 `"fenix-dsh-auth": "link:/root/dsh-plugins/fenix-dsh-auth"` 并在 `node_modules` 建符号链接（或 `dsh plugin --profile web add`）；`cordis.patch.yml` 增加 insert 行（`id: fenix-dsh-auth`、`name: fenix-dsh-auth`）
- [ ] 5.2 `systemctl restart dsh-web`（部署链既有步骤）并从 `/var/log/dsh-web.log` 尾部取新 token URL
- [ ] 5.3 playwright 命名会话（`-s` 隔离）逐 Scenario 实拍：token URL 登录成功；清 cookie 后 `/` 显示登录页且无「dsh web authentication required」文案；未配置凭据提示；设置「登录」分区配置账号密码；错误密码提示；正确密码 303 → 应用打开且 URL 不残留 token；`/api/...` 未认证仍 401；`/connect?token=` 行为不变；移除账号密码后回退为未配置提示
- [ ] 5.4 验证收尾与留档：以 token 登录态 `DELETE /auth/credentials` 清测试凭据并确认 `GET` 返回 `{configured:false}`（用户实例不留已知密码）；实拍截图落 `/root/fenixd/.history/`
- [ ] 5.5 控制台零未处理异常核查（降级路径仅 warn）

## 6. 补丁镜像与收尾（本仓）

- [ ] 6.1 `diff -ruN` 以空基线对 `/root/dsh-plugins/fenix-dsh-auth/` 现状生成 `plugin-patch/fenix-dsh-auth.patch`（含全部新建文件；不含 node_modules），并在干净目录 `patch -p1 --dry-run` 回放校验可应用
- [ ] 6.2 `plugin-patch/DEPLOY.md` 落位（部署步骤、token URL 获取、设置分区操作、回滚与卸载步骤、HTTPS 部署提示）；`BASELINE.md` 补记改后状态摘要（触达文件与改动要点、验证结论一行），确认 Deliverables 逐条对齐
