# 验证报告：add-dsh-web-password-login

> ⚠️ 本报告由框架于 2026-11-10T05:22:57Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-10T05:10:56.615465+00:00+run-result@mtime1794288162635507526

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 14/16 场景通过，2 失败，0 错误（1 个真实产品 Bug）**

16 场景 14 过 2 败。① dshauth-login-cross-origin-and-body-limits：产品 bug——超 8KB body 断连不出 400（index.js:553 req.destroy() 先于 :695/:787 writeJson 400），已复现钉死，派修复链。② dshauth-unauth-root-login-page：场景文件缺陷（headreq 步骤 curl -I -o 把 HEAD 响应头写进 -o 文件；裸 socket 复核产品 HEAD 200+零 body 正确）——已原地修复为裸 socket 取证步骤（断言集不变、经烟测），随重验证生效，不入 bug 清单。

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 2 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 6.94M |
| 本链增量 Token（输出） | 0.12M |


## 真实产品 Bug

### BUG-01（severity=major）· output_match

- 关联场景：dshauth-login-cross-origin-and-body-limits
- 描述：登录/凭据写端点对超 8KB 请求体未按 spec 返回 400 {"error":"body-too-large"}，而是直接关闭连接（curl 退出码 52、STATUS=000），客户端只收到空回复
- 根因：index.js readRequestBody 超限分支在 reject(FENIX_BODY_TOO_LARGE) 后同步 req.destroy()（index.js:553）销毁底层 socket；/auth/login 与 /auth/credentials handler 的 catch 虽有 writeJson(res, 400, 'body-too-large')（index.js:695/:787），但执行时 socket 已销毁，400 永远无法送达客户端。复现确定性命中；readRequestBody 单测仅覆盖函数级拒收、未覆盖响应送达
- 证据（场景 dshauth-login-cross-origin-and-body-limits 结构化证据，引用）：
  - failed_assertions: [{"type": "output_match", "selector": "bigbody combined 'STATUS=400'", "expected": "STATUS=400", "actual": "\\nSTATUS=000（curl 退出码 52 Empty reply，复现确定性命中）"}, {"type": "output_match", "selector": "bigbody combined body-too-large", "expected": "{\"error\":\"body-too-large\"}", "actual": "响应体为空，服务端未返回任何 400 响应"}]
  - screenshots: []
  - first_failed_step: 步骤3 bigbody：9216 字节超限 body POST /auth/login 服务端零回复断连（复现 curl 52/STATUS=000）；根因 index.js:553 readRequestBody 超限分支 req.destroy() 先于 catch 的 writeJson 400（:695/:787）销毁 socket，400 无法送达；同场景 403/text-plain 400/401 断言均过


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| dshauth-token-channel-and-baseline-reset | token 登录通道保留：从 /var/log/dsh-web.log 取当前进程 launchToken，GET /?token=<t> 原样回放原生 303 See Other + location: ./ + set-cookie（铸会话 cookie 存 jar）；随后以认证态 DELETE /auth/credentials 复位基线（幂等清理上一轮残留测试凭据，防陈旧状态污染本链）。出处：specs/dsh-web-password-login/spec.md「token 登录通道保留」Requirement；index.js:586-659 createIndexHandler、:753-836 credentials handler；2026-11-10 实测响应形态。环境依赖（dsh-web 实例 127.0.0.1:3080 在场；无 fallback——被测对象即该实例） | pass | 0/8 | - |
| dshauth-patch-mirror-deliverables | 本仓交付物三件套齐备且内容锚点在案：plugin-patch/ 下 BASELINE.md（宿主仓库基线 rev-parse HEAD/status --porcelain、部署面摘要、dsh 版本）、fenix-dsh-auth.patch（含全部六个插件文件 hunk）、DEPLOY.md（部署步骤、token URL 获取、HTTPS 部署提示、回滚/卸载）。出处：tasks.md Deliverables 与 6.1/6.2。 | pass | 0/17 | - |
| dshauth-patch-applies-clean-mirror-fidelity | 补丁镜像保真：干净目录 patch -p1 --dry-run 回放可应用（exit 0），实应用后与宿主部署态 /root/dsh-plugins/fenix-dsh-auth 逐文件 diff 零差异——镜像完整复现已部署插件。出处：tasks.md 6.1。 | pass | 0/3 | - |
| dshauth-unauth-root-login-page | 未认证首页呈现登录页：无 cookie GET / 返回 200 text/html 登录页（用户名/密码输入与提交按钮齐备），不出现原生 401 文案「dsh web authentication required; reopen the URL printed by dsh web.」，页面不含 ?token= 值、无 CSS animation/transition（静态渲染红线），凭据未配置（上一步已复位）时带「未配置账号密码」提示；HEAD / 仅响应头、无 body。出处：spec.md「未认证首页呈现登录页」Requirement 三 Scenario；index.js:202-252 renderLoginPage、:499-506 writeNativeUnauthorized、:508-518 writeLoginPage。环境依赖（dsh-web 实例 127.0.0.1:3080 在场；无 fallback） | failed（已修正） | 3/17 | test-defect |
| dshauth-plugin-unit-tests | 插件单测全绿：在补丁回放树以 node --test 原生 glob 形态（node 24.19 对目录 positional 不做测试发现，tasks.md 4.2 注解）运行 tests/host.test.mjs，14/14 通过、0 失败（scrypt 哈希/校验、限流窗口、登录页无 token 无动画、转义白名单、8KB 限读、同源判定）。出处：tasks.md 4.1/4.2。 | pass | 0/3 | - |
| dshauth-activation-contract-and-degradation | 装配与降级契约（进程内桩 ctx 探针）：六项上游契约齐备时 apply 注册三 exact 路由 /、/auth/login、/auth/credentials 且 disposer 可卸载；契约缺失（connection/credentials 方法缺型）时同步零注册（降级保持原生 token-only，无未处理异常）。客户端半静态契约：settings.section 分区注册、/auth/credentials 三方法接线、移除前 window.confirm、confirm-mismatch 提示文案、无 animation:/transition: 内联样式、不注入全局 <style>。部署配置在案：profile package.json 的 link 依赖与 cordis.patch.yml insert 行。出处：spec.md「上游契约失配降级」Requirement；tasks.md 2.2/3.1/5.1；index.js:362-460。 | pass | 0/15 | - |
| dshauth-login-get-error-whitelist | GET /auth/login 无需认证即返回登录页；?error= 白名单文案：invalid→「用户名或密码错误」、locked→「失败次数过多，请 60 秒后重试」、unconfigured→「未配置账号密码：请先用 token URL 登录…」；白名单外的反射值（如 %3Cscript%3E）不落页（无 error 段、无 <script> 反射）。出处：spec.md「账号密码登录与自动带 token」Requirement GET 条款；index.js:66-71 LOGIN_ERROR_MESSAGES、:190-194 normalizeLoginError、:671-677。环境依赖（dsh-web 实例 127.0.0.1:3080 在场；无 fallback） | pass | 0/7 | - |
| dshauth-credentials-endpoint-contract | 凭据端点契约：未认证 GET/POST /auth/credentials 均 401 且不回显任何凭据；认证态 POST 参数校验（密码<8→400 password-too-short、confirm 不一致→400 confirm-mismatch、用户名 65 字符→400 invalid-username）；合法 POST 保存成功返回 {configured:true,username}，回读一致且响应不含明文密码。出处：spec.md「设置分区账号密码配置」Requirement 端点条款与「校验失败提示」「未认证调用凭据接口」Scenario；index.js:753-836。环境依赖（dsh-web 实例 127.0.0.1:3080 在场；无 fallback） | pass | 0/13 | - |
| dshauth-credentials-scrypt-no-plaintext | 凭据哈希存储不落明文：上一步配置后，dsh 凭据文件 /root/.dsh/.credentials.yaml 的 fenix-dsh-auth/login 记录含 kind: grant、salt/hash/N: 16384（scrypt 参数在案），全文件 grep 不到测试明文密码（窄 grep 取证，不整读文件防其他密钥入证据）。出处：spec.md「凭据哈希存储与失败限流」Requirement 与「凭据不落明文」Scenario；index.js:50-51 SCRYPT_PARAMS、:800-804。环境依赖（dsh-web 实例 127.0.0.1:3080 在场；无 fallback） | pass | 0/15 | - |
| dshauth-configured-root-no-unconfigured-hint | 已配置态首页回归：凭据已配置时未认证 GET / 仍返回 200 登录页（表单锚点在），但不再显示「未配置账号密码」提示（与未配置态区分）。出处：spec.md「未认证首页呈现登录页」Requirement index.js:642-647 configured 分支。环境依赖（dsh-web 实例 127.0.0.1:3080 在场；无 fallback） | pass | 0/5 | - |
| dshauth-login-wrong-password-invalid | 错误密码路径：POST /auth/login（urlencoded，同源）错误密码 → 303 location /auth/login?error=invalid；不存在的用户名 + 错误密码 → 同样 error=invalid（不泄漏账号是否存在）；跟随重定向的登录页显示统一错误「用户名或密码错误」。出处：spec.md「错误密码」Scenario；index.js:715-725。环境依赖（dsh-web 实例 127.0.0.1:3080 在场；无 fallback） | pass | 0/5 | - |
| dshauth-login-correct-password-auto-token | 正确密码登录自动带 token：POST /auth/login 正确凭据 → 303 Location 含 /?token=<launchToken>（URL 自动加上 token）；curl 跟随完整重定向链（303→/?token=→原生 303 铸 cookie→./）后终态 200 落在干净 URL http://127.0.0.1:3080/（地址栏不残留 token），最终页面为 dsh web 应用首页（含 base href="./"）而非登录页；会话 cookie 已铸入 jar 供后续场景消费。出处：spec.md「正确密码登录成功」Scenario；design.md D4；index.js:727-736 authenticatedUrl。环境依赖（dsh-web 实例 127.0.0.1:3080 在场；无 fallback） | pass | 0/6 | - |
| dshauth-login-cross-origin-and-body-limits | 登录与凭据写端点防护：跨源 Origin（http://evil.example）POST /auth/login → 403 {"error":"cross-origin"}（不进行凭据校验）；Content-Type 白名单外（text/plain）→ 400 unsupported-body；请求体超 8KB → 400 body-too-large；跨源 POST /auth/credentials → 403。出处：spec.md「跨源提交拒绝」Scenario 与「账号密码登录与自动带 token」Requirement 400 条款；index.js:684-701、:777-782。环境依赖（dsh-web 实例 127.0.0.1:3080 在场；无 fallback） | failed（已修正） | 2/8 | product-bug |
| dshauth-rate-limit-lock | 失败限流：同源 60 秒窗口内连续 5 次错误密码 → 每次均 303 error=invalid；第 6 次提交（即使密码正确）→ 303 location /auth/login?error=locked（锁定期间正确密码也拒绝）。出处：spec.md「失败限流」Scenario；design.md D8；index.js:60-64 RATE_* 常量、:705-707。环境依赖（dsh-web 实例 127.0.0.1:3080 在场；无 fallback） | pass | 0/4 | - |
| dshauth-remove-credentials-fallback | 移除账号密码回退 token-only：认证态 DELETE /auth/credentials → 200 {"configured":false}（同时清该来源限流）；回读 configured:false、username:null；未认证 GET / 回到「未配置账号密码」提示态；token 通道仍可用（GET /?token → 303 + set-cookie）；限流已清零（错误密码登录回到 error=invalid 而非 locked）——同时完成测试凭据收尾清理（用户实例不留已知密码）。出处：spec.md「移除账号密码」Scenario；design.md D9；index.js:809-824。环境依赖（dsh-web 实例 127.0.0.1:3080 在场；无 fallback） | pass | 0/12 | - |
| dshauth-native-contracts-unchanged | 回归面：原生契约与插件接管前一致——未认证 /api 走原生 401（不落登录页）、/connect token 交换行为不变（实测 302 Found 而非 spec 猜测的 303，契约口径是「行为一致」非字面状态码）、/index.html 原生入口不被接管；收尾幂等清理。环境依赖（dsh-web 实例 127.0.0.1:3080 在场；无 fallback——被测对象即该实例） | pass | 0/9 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| dshauth-unauth-root-login-page | exit_code [headreq] HEAD / 无 body 校验 | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景文件缺陷：curl -I 对 HEAD 把头块写进 -o 文件（复测 -I -D - -o 头进 stdout 且文件 243 字节），文件非空致 test 失败退出 1；裸 socket 复核产品 HEAD 行为正确 |
| dshauth-unauth-root-login-page | output_match [headreq] 'HTTP/1.1 200 OK' | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景文件缺陷：头被 -o 重定向走致 stdout 空（actual 仅换行）；裸 socket 探针取得 HTTP/1.1 200 OK 状态行在案，服务端非未回 200 |
| dshauth-unauth-root-login-page | output_match [headreq] 'HEAD_BODY_EMPTY' | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景文件缺陷：head_body.bin 被响应头占据非空致 test ! -s 为假；裸 socket 复核 header 后零 body 字节，已改写步骤令 body 落盘断言真实成立 |

## 本轮场景集变更

当前稳定场景集共 16 个（第 1 轮）。

- 首轮写入 16 个场景

