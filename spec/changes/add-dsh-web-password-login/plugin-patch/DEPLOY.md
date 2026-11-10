# DEPLOY — fenix-dsh-auth 部署指南

> 适用于 dsh 0.2.2-rc.1（宿主版本契约见 `BASELINE.md` §2；engines 声明 `>=0.2.0-rc.0 <0.3`）。
> 插件源码由 `fenix-dsh-auth.patch` 在空目录 `patch -p1` 一键落地（见 §1）。

## 0. 前置条件

- dsh web 已安装且 `dsh-web.service` 正常运行（默认监听 `127.0.0.1:3080`）。
- 若经反向代理访问 dsh web：代理必须**透传 `Host` 头**（不得改写为上游地址），否则同源校验（Origin vs Host）恒判跨源，登录 POST 一律 403。`Origin` 头同理不删改。
- HTTPS 部署提示：插件监听协议由 webServer 决定，http/https 均可。若在反代终止 TLS、上游仍为 http，浏览器 Origin 为 `https:` 而 Host 判定按上游 `http:`——插件按**端口归一化比较主机与端口**（协议不同判跨源）。此类拓扑需在反代上保持 scheme 一致（`X-Forwarded-Proto` 不参与判定），或将反代配置为同 scheme 回源。
- token 登录通道保持完整可用；本插件为**增量**登录通道，未配置账号密码时行为与原生完全一致。

## 1. 安装插件源码（补丁落地）

```bash
mkdir -p /root/dsh-plugins/fenix-dsh-auth
cd /root/dsh-plugins/fenix-dsh-auth
patch -p1 --dry-run < /path/to/fenix-dsh-auth.patch   # 预检
patch -p1 < /path/to/fenix-dsh-auth.patch             # 落地 6 文件
```

落地后目录应含：`package.json`、`index.js`、`client.js`、`cordis.patch.yml`、`README.zh.md`、`tests/host.test.mjs`。

自检（可选）：

```bash
cd /root/dsh-plugins/fenix-dsh-auth
node --test 'tests/**/*.test.mjs'    # 14/14 全绿
```

> 注意：node ≥24 对 `node --test <目录>` 不做测试发现，必须用上式 glob 形态。

## 2. 注册到 web profile

三处改动（`/root/.dsh/profiles/web/`）：

**① `package.json` — dependencies 加 link 依赖**（字母序插入）：

```json
"fenix-dsh-auth": "link:/root/dsh-plugins/fenix-dsh-auth"
```

**② node_modules 建链**：

```bash
ln -s /root/dsh-plugins/fenix-dsh-auth /root/.dsh/profiles/web/node_modules/fenix-dsh-auth
```

**③ `cordis.patch.yml` — insert 块加插件条目**（放在现有条目列表尾即可）：

```yaml
- insert:
    # ...现有条目...
    - id: fenix-dsh-auth
      name: fenix-dsh-auth
```

## 3. 重启并获取 token URL

```bash
systemctl restart dsh-web
grep 'dsh web: http' /var/log/dsh-web.log | tail -1
# → dsh web: http://127.0.0.1:3080/?token=<新 token>
```

**token 每次重启轮换**；重启后旧 token 失效，以日志尾部最新一行为准。

启动日志核查：不得出现 `fenix-dsh-auth` 相关 Error 或 `entry did not activate`。

## 4. 配置账号密码（登录后操作）

1. 用上面的 token URL 打开 dsh web（完成 token 登录）。
2. 左下角账户菜单 → **Settings**。
3. 设置弹窗导航尾部的 **「登录」** 分区（General / Models 之后）。
4. 填写用户名（1–64 字符）、密码（≥8 字符）、确认密码 → **保存**。
5. 状态行变为「已配置账号密码：<用户名>」即生效；新浏览器会话访问根路径将直接得到登录页。

## 5. 验证清单（部署后快速验收）

| 检查 | 预期 |
| --- | --- |
| 无 cookie 打开 `http://<host>:3080/` | 登录页（标题「dsh web 登录」，无原生 401 文案） |
| 登录页提示 | 已配置→仅表单；未配置→引导先用 token URL 登录 |
| 错误密码提交 | 回登录页 `?error=invalid`，提示「用户名或密码错误」 |
| 正确密码提交 | 303 → 应用打开，URL 不残留 token |
| 未认证访问 `/api/*` | 401（原生不变式保留） |
| `systemctl restart` 后 | token URL 轮换；账号密码凭据持久保留 |

## 6. 回滚 / 卸载

**仅停用账号密码登录（保留插件文件）**：删除 cordis.patch.yml 中 `fenix-dsh-auth` 两行 insert 条目 → `systemctl restart dsh-web`。启动时插件不再装载，行为回到纯 token 通道。

**完全卸载**：

1. cordis.patch.yml 删除 insert 条目（同上）。
2. `package.json` dependencies 删除 `fenix-dsh-auth` 行。
3. `rm /root/.dsh/profiles/web/node_modules/fenix-dsh-auth`（删链接，勿删 `-r` 源目录）。
4. `rm -rf /root/dsh-plugins/fenix-dsh-auth`。
5. 清除凭据文件中的残留键 `<dsh_home>/.credentials.yaml` 的 `fenix-dsh-auth/login` 段（如曾配置）。
6. `systemctl restart dsh-web`，以日志新 token URL 登录确认回到原生形态。

> 安全注记：凭据存储为 scrypt(N=16384,r=8,p=1,keylen=64) + 16B 随机盐，hex 字符串落于 `<dsh_home>/.credentials.yaml`（与官方凭据同文件）；移除账号密码后回退纯 token 登录，旧密码哈希同步删除。
