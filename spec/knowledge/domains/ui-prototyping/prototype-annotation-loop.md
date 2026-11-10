# 原型批注环

<!-- knowledge: capability=prototype-annotation-loop rev=3
     sources=spec/archive/2026-11-02-fenix-prototype,spec/knowledge/_inbox/done/ops-mobile-nested-bento-removal.md,spec/knowledge/_inbox/done/proto-serving-via-dashboard.md -->

原型草稿的会话内批注迭代闭环：dashboard 常驻进程承载原型伺服、注入式批注器收集意见、`feedback.json` 回流驱动修订，直到用户明示批准入库并冻结。

## 规则

### 原型伺服（dashboard 承载）

- 原型不独立启动 HTTP 服务器：原型目录 `<工程根>/.fenix/prototypes/<spec>/` 由 fenix dashboard 常驻进程经 `GET /proto/<project>/<spec>/<file>` 路由伺服，恒 no-cache——改原型即时生效，无需重启 dashboard。
- 原型伺服依赖 dashboard 的 `/proto/` 路由；不带该路由的旧版本 dashboard 对原型 URL 返回 404（proto_serve 退出码 5 的典型成因，hint 提示升级/核对）。
- 原型伺服零生命周期管理：dashboard 由 systemd 常驻（unit `fenix-dashboard.service`），无起服、回收与残留进程问题；批准入库流程不含「回收服务器」步骤。
- 远程访问只需一条指向 dashboard 端口的既有隧道（dashboard 只绑 127.0.0.1、端口固定），即可覆盖所有原型，不按原型逐个转发随机端口。

### 批注落盘端点

- 批注端点为 `POST /api/proto/<project>/<spec>/feedback`；走 `/api/` 前缀是硬约束——dashboard 对非 api 路径的 POST 一律 405。
- 落盘 IO 单源 `core/dashboard/prototype_io.py`：读-改-写持线程锁 + 跨进程 flock（伴生 `.lock` 文件）串行；总量上限 8MB，超限拒绝写入（507）；损坏文件写入前改名隔离为 `<名>.corrupt-<ts>.<pid>.<tid>.bak`；list 形态追加、`{"feedback":[...]}` dict 形态保留结构回写、不含 feedback 列表的 JSON object 拒绝写入（409）。

### URL 形态与静态白名单

- 入口 URL 为 `http://127.0.0.1:<port>/proto/<project>/<spec>/?proto_round=N`（index 页目录形态）；子页 `/proto/<project>/<spec>/<page>.html?proto_round=N`。
- 目录形态无尾斜杠时 301 补斜杠并保留 query（浏览器相对资源基与轮次迭代参数不丢失）。
- 静态伺服按扩展名白名单 `PROTOTYPE_FILE_TYPES` 放行前端资产（html/css/js/json/svg/png/webp/gif/ico/woff 等）；`feedback.json` 及其派生名（`.bak`/`.lock`）静态通道 GET 一律 403，批注数据不被静态通道读走。

### 地址生成（skill 侧）

- `skills/fenix-prototype/scripts/proto_serve.py` 只做原型地址生成与验证，不起任何进程。
- 端口候选链：`--dashboard-port` 参数 > `~/.config/fenixd/dashboard.yaml` 顶层 `port:` > 8787。
- 验证链：探测 `GET /api/projects`（200 且含 `projects` 列表）→ 按 realpath 匹配已注册项目名 → 端到端 GET 原型 URL 验证 200 才输出。
- 退出码：0 ok / 2 输入错（原型目录缺失、无 HTML）/ 3 dashboard 不存活 / 4 项目未注册 / 5 URL 验证失败（含旧版 dashboard 无 `/proto/` 路由的情形）。
- 兼容旧调用形态的 `--json` 为无副作用占位开关，输出恒为 JSON。

### 批注器与会话内迭代

- 批注器为注入式通用 JS（annotator.js），与组件栈无关（纯 DOM 操作）：hover 高亮、点选元素、意见输入面板、意见列表、提交批注；批注以目标元素 `data-proto-id` 锚点为主键，同时记录时间戳与轮次。
- annotator.js 端点自适应：按 `location.pathname` 匹配 `^/proto/([^/]+)/([^/]+)(?:/|$)` 推导 POST 端点 `/api/proto/<m1>/<m2>/feedback`（捕获段原样传递，与服务端单次 unquote 对上）；不匹配时兜底 `/feedback`。
- 批注端点不可达时（如以 file:// 直接打开原型）降级为本地导出 JSON 文件，用户可把文件交给 agent。
- 批注回流后 agent 读取 `feedback.json` 修订原型，用户刷新浏览器复看，循环直到用户明示认可；每轮修订遵守重生成锚保持要求；迭代全部发生在当前会话内，不依赖异步审批流。

### 批准入库与冻结

- 仅当用户在会话中明示认可（如「原型定了」）才视为批准。批准后原型文件连同整页截图落入 `specs/<spec>/prototype/` 入库提交，草稿目录（`.fenix/prototypes/<spec>/`，gitignore 运行时目录）清理。
- 整页截图尽力而为：无头浏览器不可用或抓取失败时批准不阻塞，SPEC 显式记录「无渲染凭证」降级，HTML 仍为真相源主体。
- 批准后原型视为冻结：任何再修改视为新一轮确认（重新迭代、重新批准），不静默改动已入库原型。

### 控制台噪音判读

- 原型页控制台的 vendor DEV 构建警告为非缺陷信号：react DEV 构建（vendor 缓存/CDN 加载）对 createElement 多位置 children 写法恒发一条「数组 key」警告，已入库旧版原型同款、生产构建不含 DEV React 无此噪音——排查页面代码前先与旧版原型控制台对照，勿据该警告返工。

## 代码锚点

- 主实现：`core/dashboard/routes/static_routes.py`（`_serve_prototype` 静态伺服，挂 `core/dashboard/routes/base.py` `_handle_inner` 的 `/proto/` 分支、SPA fallback 之前；`_api_proto_feedback` 批注落盘，经 `base.py` `_API_POST_ROUTES` regex 条目路由）
- 落盘 IO 单源：`core/dashboard/prototype_io.py`（静态白名单 `PROTOTYPE_FILE_TYPES` 同在此单源）
- skill 侧地址生成：`skills/fenix-prototype/scripts/proto_serve.py`；批注器 `skills/fenix-prototype/assets/annotator.js`
- 守卫测试：`tests/test_fenix_prototype.py`、`tests/test_dashboard_prototype_routes.py`、`tests/test_dashboard_api.py`

## 溯源

- 2026-11-02 fenix-prototype（spec/archive/2026-11-02-fenix-prototype） — 新增本能力：独立简易服务器与 PID 三态生命周期、注入式批注器与本地导出降级、feedback.json 会话内迭代闭环、批准入库与冻结语义。
- 2026-11-07 ops-mobile-nested-bento-removal（spec/knowledge/_inbox/done/ops-mobile-nested-bento-removal.md） — 新增控制台噪音判读条款：vendor React DEV「数组 key」警告为非缺陷信号，排查先对照旧版原型控制台、勿据其返工
- 2026-11-10 proto-serving-via-dashboard（spec/knowledge/_inbox/done/proto-serving-via-dashboard.md） — 伺服形态覆盖重写：独立 HTTP 服务器与 PID 生命周期管理退役，改由 dashboard 常驻进程 `/proto/` 路由承载（恒 no-cache、静态白名单、批注端点 `/api/` 前缀硬约束、prototype_io 落盘单源），skill 侧 proto_serve 只做地址生成与验证（退出码 0/2/3/4/5），远程访问单隧道覆盖全部原型
