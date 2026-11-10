# BASELINE — fenix-dsh-auth 宿主基线快照

> 快照时刻：2026-11-10（add-dsh-web-password-login 实现 run，改动前状态）
> 宿主仓库：`/root/dsh-plugins`（跨仓实现面，本 SPEC 宿主半直改落点）
> 部署面：`/root/.dsh/profiles/web/`（宿主运行配置，非本仓交付物，仅摘要留档）

## 1. 宿主仓库基线

```
$ git -C /root/dsh-plugins rev-parse HEAD
5ae9e41bd5213b3faf0bcef4d9e2465bbcd8f8d5

$ git -C /root/dsh-plugins status --porcelain
 M fenix-dsh-brand-fenix/client.js
 M fenix-dsh-chat-polish/client.js
 M fenix-dsh-dashboard-bridge/src/client/index.ts
 M fenix-dsh-dashboard-bridge/src/client/panels.tsx
 M fenix-dsh-dashboard-bridge/src/client/projectSync.ts
 M fenix-dsh-dashboard-bridge/tests/projectSync.test.ts
 M fenix-dsh-dashboard-bridge/tests/srcContract.test.ts
?? .claude/
```

- 上述 7 个 M 条目与本 SPEC 无关（既有工作区滞留改动，本 SPEC 不触碰这些文件）。
- **`/root/dsh-plugins/fenix-dsh-auth/` 在基线时刻不存在**（`ls` 确认 No such file or directory），清单中无同名插件——本 SPEC 新建该目录，全部文件为新增。

## 2. 部署面现状摘要（改动前）

### `/root/.dsh/profiles/web/package.json`

- `dependencies` 键集合（8 项）：`billion-context`、`cc-import`、`dsh-plugin-loopback-trust`、`dshmarket`、`fenix-dsh-chat-polish`、`fenix-dsh-dashboard-bridge`、`fenix-dsh-session-grouper`、`fenix-skill-provider`。
- **无 `fenix-dsh-auth` 依赖**（改动前）。
- `dsh.profile.bundles`（11 项）：`@deepseek-ai/dsh-base`、`@deepseek-ai/dsh-web-app`、`@deepseek-ai/dsh-experimental-agent-team-profile`、`@deepseek-ai/dsh-experimental-auto-review`、`@deepseek-ai/dsh-experimental-voice-input-bundle`、`dsh-plugin-loopback-trust`、`fenix-dsh-chat-polish`、`dshmarket`、`billion-context`、`@deepseek-ai/dsh-experimental-forge-bundle`、`@deepseek-ai/dsh-experimental-plugin-market-bundle`。
- **`dsh.profile.bundles` 不含 `fenix-dsh-auth`**（改动前）。

### `/root/.dsh/profiles/web/cordis.patch.yml` insert 行清单

`- insert:` 块（原第 8–22 行）共 7 个插件条目，**无 `fenix-dsh-auth`**（改动前）：

| 行号（原文件） | id | name |
| --- | --- | --- |
| 9–10 | `cc-import` | `cc-import` |
| 11–12 | `fenix-dsh-dashboard-bridge` | `fenix-dsh-dashboard-bridge` |
| 13–14 | `fenix-dsh-chat-polish` | `fenix-dsh-chat-polish` |
| 15–16 | `fenix-dsh-brand-fenix` | `fenix-dsh-brand-fenix` |
| 17–18 | `fenix-skill-provider` | `fenix-skill-provider` |
| 19–20 | `fenix-dsh-session-grouper` | `fenix-dsh-session-grouper` |
| 21–22 | `fenix-dsh-settings-dock` | `fenix-dsh-settings-dock` |

其余 patch 条目（`ui-settings-general`、`llm-pi-ai`、`ui-theme`、`permission`、`remote-ssh`、`agent-default-model`）与本 SPEC 无关，不触碰。

### dsh 版本

```
$ node /usr/bin/dsh --version
0.2.2-rc.1
```

上游安装位置：`/usr/lib/node_modules/@deepseek-ai/dsh`（不修改）。

### 运行态（快照时刻）

- `dsh-web.service`：loaded active running（profile web，监听 port 3080，frp dsh-web proxy upstream）。
- 日志：`/var/log/dsh-web.log`。

## 3. 改后状态摘要（收尾补记）

### 宿主仓库 `/root/dsh-plugins/fenix-dsh-auth/`（新建）

| 文件 | 内容 |
| --- | --- |
| `package.json` | 零构建插件清单：exports `.`→index.js / `./client`→client.js；`dsh.bundle.patch` 指向 cordis.patch.yml；`dsh.client`（platform web、inject `@deepseek-ai/dsh-client-ui-settings-general`）；engines `dsh >=0.2.0-rc.0 <0.3` |
| `index.js` | 宿主半：exact `/` 认证委派（authorizeIndex→admit→readResource）、`/auth/login`（GET/HEAD 登录页 + POST 同源校验/8KB 限读/限流/scrypt 校验/303）、`/auth/credentials`（GET/POST/DELETE，admit 门 + modifyRecord/deleteRecord）；契约探测走 `ctx.get()` 防「without inject」throw；未就绪 200ms×50 轮询后 warn 降级 token-only |
| `client.js` | 客户端半：`inject: ['slots']` 声明（浏览器侧 cordis 同样要求，缺失即 boot failed）；settings.section / settings.section.icon 双槽注入（逐槽 try/catch 降级）；AuthSection 组件（状态回填/保存/移除/401-400-403 提示）；order 动态探测官方尾+1，回退 16 |
| `cordis.patch.yml` | `insert: fenix-dsh-auth` 单条 |
| `README.zh.md` | 能力/部署/安全边界/回滚说明 |
| `tests/host.test.mjs` | node:test 单测 14 例（scrypt/限流/登录页不变式/转义/错误码白名单/请求体解析/同源判定/凭据 key） |

基线中 7 个 M 文件未触碰；本 SPEC 在宿主仓仅新增上述目录（宿主仓不提交，交付以本目录 `fenix-dsh-auth.patch` 镜像为准）。

### 部署面改动

1. `/root/.dsh/profiles/web/package.json`：`dependencies` 新增 `"fenix-dsh-auth": "link:/root/dsh-plugins/fenix-dsh-auth"`（8→9 项，字母序）；`bundles` 未动（插件非 bundle）。
2. `/root/.dsh/profiles/web/node_modules/fenix-dsh-auth`：新建符号链接 → `/root/dsh-plugins/fenix-dsh-auth`（绝对路径，fenix-dsh-settings-dock 同款形态）。
3. `/root/.dsh/profiles/web/cordis.patch.yml`：insert 块尾新增 `- id: fenix-dsh-auth` / `  name: fenix-dsh-auth`（7→8 条）。

### 验证状态（2026-11-10）

- `systemctl restart dsh-web` 后：启动日志零插件错误（对照：修复前历史日志含 `cannot get property "connection" without inject` 与客户端 `boot: 1 entry did not activate` 两条已消除）。
- playwright 四会话 console 全零（0 errors / 0 warnings），覆盖 token 登录、设置分区配置/移除、密码登录全流程。
- 服务端路由行为（curl 实证）：未认证 `/`→登录页（无原生 401 文案）；未认证 `/api/sessions`→401（原生不变式保留）；`/connect?token=`→302 `./api/remote.mux`（官方行为不变）；token URL→303+set-cookie；错误密码→303 `?error=invalid`；跨源 POST→403；HEAD `/auth/login`→200 仅头无 body（`referrer-policy: same-origin`）。
- 单测 14/14 全绿（源树与补丁回放树各跑一遍）。
- 测试凭据收尾已清理：`GET /auth/credentials`（认证态）→ `{"configured":false,"username":null}`，实例不留已知密码。
- 截图证据：`/root/fenixd/.history/dshauth-01…11-*.png`（11 张，主树 `.history`，不提交）。

已知踩坑记录（修复于实现期，代码已含防回归断言）：

1. 宿主半未声明 inject 时直接访问 `ctx.connection` 抛 `cannot get property "connection" without inject`——契约探测必须走 `ctx.get(name)`。
2. 客户端半返回对象同样必须声明 `inject: ['slots']`，否则浏览器侧 boot `entry did not activate`。
3. 登录页 `<meta name="referrer" content="no-referrer">` 会让浏览器把本页 form POST 的 Origin 头置为 `null`（opaque origin），触发服务端跨源 403——policy 必须用 `same-origin`（响应头同步），单测已加 `no-referrer` 禁用断言。
4. node 24.19 的 `node --test <dir>` 目录 positional 不做测试发现（MODULE_NOT_FOUND），须用 `node --test 'tests/**/*.test.mjs'` 原生 glob。

