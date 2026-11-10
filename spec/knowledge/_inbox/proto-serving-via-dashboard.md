# 原型伺服迁移 dashboard 承载（fenix-prototype skill 形态变更）

## 背景

fenix-prototype skill 原形态（prototype-annotation-loop.md rev2 所记）：每轮原型
确认由 `serve_prototype.py` 起一个**独立 python stdlib HTTP 服务器**（随机高端口），
用户远程访问需要为每个原型单独做 SSH 端口转发，体验差、留残留进程、还要在批准时
回收。2026-11-10 经 add-proto-dashboard-serving 改造（commit c4f42f98c + 785ae5cf0）
迁移到 fenix dashboard 常驻进程承载。

## 结论（当前事实）

- 原型**不独立启动 HTTP 服务器**。原型目录 `<工程根>/.fenix/prototypes/<spec>/` 由
  fenix dashboard 常驻进程经 `GET /proto/<project>/<spec>/<file>` 路由伺服，恒
  no-cache（改原型即时生效，无需重启 dashboard）。
- 实现落点（框架侧）：静态伺服 `core/dashboard/routes/static_routes.py`
  `_serve_prototype`（挂 base.py `_handle_inner` 的 `/proto/` 分支，SPA fallback
  之前）；批注落盘端点 `POST /api/proto/<project>/<spec>/feedback`（base.py
  `_API_POST_ROUTES` regex 条目 → `_api_proto_feedback`）；落盘 IO 单源
  `core/dashboard/prototype_io.py`（flock 伴生 .lock、8MB 上限 507、corrupt 隔离
  `.corrupt-<ts>.<pid>.<tid>.bak`、list 形态追加 / `{"feedback":[...]}` dict 形态
  保留结构回写 / 其他 dict 409）。批注端点走 `/api/` 前缀是硬约束：dashboard
  非 api 路径的 POST 一律 405。
- 实现落点（skill 侧）：`skills/fenix-prototype/scripts/proto_serve.py` 只做
  **地址生成与验证**，不起进程：端口候选链 `--dashboard-port` >
  `~/.config/fenixd/dashboard.yaml` 顶层 `port:` > 8787；探测 `GET /api/projects`
  （200 且含 `projects` 列表）；按 realpath 匹配已注册项目名；最后端到端 GET
  原型 URL 验证 200 才输出。退出码：0 ok / 2 输入错（原型目录缺失、无 HTML）/
  3 dashboard 不存活 / 4 项目未注册 / 5 URL 验证失败。兼容旧调用形态的 `--json`
  为无副作用占位开关（输出恒为 JSON）。
- URL 形态：`http://127.0.0.1:<port>/proto/<project>/<spec>/?proto_round=N`
  （index 页目录形态，无尾斜杠 301 补斜杠且保留 query，保证浏览器相对资源基
  正确）；子页 `/proto/<project>/<spec>/<page>.html?proto_round=N`。静态白名单
  `PROTOTYPE_FILE_TYPES`（html/css/js/json/svg/png/webp/gif/ico/woff 等前端资产），
  `feedback.json` 及其派生名（.bak/.lock）GET 屏蔽 403，防批注数据被静态通道读走。
- annotator.js 端点自适应：按 `location.pathname` 匹配
  `^/proto/([^/]+)/([^/]+)(?:/|$)` 推导 POST 端点 `/api/proto/<m1>/<m2>/feedback`
  （捕获段原样传递，与服务端单次 unquote 对上）；不匹配时兜底 `/feedback`
  （file:// 直开走本地导出降级，不参与）。
- 生命周期零管理：dashboard systemd 常驻（unit `fenix-dashboard.service`），
  无起服/回收/残留进程问题；§6 批准入库不再有「回收服务器」步骤。
- 远程访问：dashboard 只绑 127.0.0.1、端口固定，远程客户端只需**一条**指向
  dashboard 端口的既有隧道即可覆盖所有原型，不再按原型逐个转发随机端口。
- `serve_prototype.py` 已退役删除（spec/archive 历史文档中的引用保持原样不改）。
- dashboard 承载伺服对**旧版本 dashboard 会 404**（无 `/proto/` 路由）——
  proto_serve 退出码 5 的语义即此，hint 提示升级/核对。

## 证据

- 端到端（真实 systemd 实例 127.0.0.1:8787，PPID=1）：`proto_serve.py --project
  /root/fenixd --spec <spec> --json` → `{"ok":true,"url":"http://127.0.0.1:8787/
  proto/fenixd/<spec>/?proto_round=1",...}`；GET URL 200 text/html；GET
  annotator.js 200 application/javascript；无尾斜杠 301 `Location` 保留
  `?proto_round=2`；POST 批注 → `{"ok":true,"stored":".../feedback.json"}` 且
  落盘内容含 anchor/text/round。
- 回归：`tests/test_fenix_prototype.py` + `tests/test_dashboard_prototype_routes.py`
  + `tests/test_dashboard_api.py` 282 passed（2026-11-10）。
- 关键提交：c4f42f98c（框架侧+skill 脚本收编）、785ae5cf0（SKILL.md §4/§5/§6.2
  改写、serve_prototype 删除、proto_serve REPO_ROOT parents[3] 修正、测试
  HOME+DEFAULT_PORT 双隔离）。
- 教训两条：① `REPO_ROOT = parents[2]` 在 `skills/<skill>/scripts/` 三层目录下
  得到的是 `skills/` 目录，仓库根是 `parents[3]`——off-by-one 曾让 hint 拼出
  `skills/bin/fenix_dashboard.py` 不存在路径；② 测试里探测「dashboard 不存活」
  时，宿主机可能真有 dashboard 占着 8787（配置文件 `port: 8787` 也在候选链），
  须 monkeypatch `DEFAULT_PORT` 并把 HOME 钉到 tmp 双隔离，否则候选链兜底探到
  真实实例后走的是另一条分支。
