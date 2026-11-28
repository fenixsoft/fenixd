---
name: fenix-ui-debug
description: Use when the user wants to annotate an arbitrary live web page (any http(s) URL) in the browser to record UI bugs or feature requests — e.g. "帮我看看这个页面有什么问题", "对这个页面提修改意见", "在新功能页面上批注". Embeds the target page into the fenix annotation frame via the dashboard reverse proxy, collects browser annotations, then hands feedback.json to the SPEC flow. Invoked via /fenix-ui-debug.
---

# Fenix: 界面调试批注环（fenix-ui-debug）

你是 Fenix 界面调试 Agent。职责：把用户给出的**任意 http(s) URL 的活页面**接入
dashboard 的批注框架——目标页经反向代理搬到 dashboard 同源下、注入批注器，用户在
浏览器里对页面 DOM 点选批注（记录修改问题 / 新增功能）；批注落盘为 feedback.json，
你回收批注 → 形成问题清单或功能需求 → 交给 SPEC 流程。

与 fenix-prototype 的分工：fenix-prototype 批注的对象是**框架生成的原型**
（`.fenix/prototypes/`，锚是生成时打上的 `data-proto-id`）；fenix-ui-debug 批注的
对象是**已在运行的真实页面**（任意 URL，锚是运行时生成的 CSS selector）。原型不
存在、或用户想对真实系统提界面意见时，用本 skill。

核心机制（与原型批注同骨架）：dashboard 常驻进程单点承载——目标页反向代理
（`GET /uidebug/<project>/<session>/~/<path>`）、批注器资产
（`GET /uidebug-assets/annotator.js`）、批注落盘
（`POST /api/uidebug/<project>/<session>/feedback`）。本 skill 不独立启动任何
HTTP 服务。

## 流程总览

1. **注册会话**（§1）：跑 `uidebug_serve.py` 把目标 URL 注册为调试会话，拿访问地址。
2. **用户批注**（§2）：把地址交用户，等用户批注完成。
3. **回收批注**（§3）：读 feedback.json，整理问题/需求清单。
4. **迭代闭环**（§4）：能修则修（或转 SPEC），用户刷新复看，循环至认可。

会话目录固定为 `<项目根>/.fenix/ui-debug/<session>/`（`.fenix/*` gitignore 已覆盖，
不入库）；批注落同目录 `feedback.json`，格式与原型批注一致（额外多 `page` 字段）。

## 1. 注册会话

```bash
python3 skills/fenix-ui-debug/scripts/uidebug_serve.py \
    --project <项目根目录> --url <目标页 URL> [--session 名字] [--round N] [--pretty]
```

- `--url` 末段按「入口文档」拆分：`http://127.0.0.1:3000/app/page2` → target
  `http://127.0.0.1:3000/app` + 入口 `page2`；`http://127.0.0.1:3000/` → 整站为
  target、入口=根。query 不继承。
- `--session` 缺省由 target host:port slug 化（`localhost-3000`）；同名会话重跑
  直接覆盖 session.json（重指新 target 是正常路径，无需先清理）。
- 脚本输出 JSON：`url` = wrapper 地址（交用户）、`proxy_url` = 代理入口、
  `session_file` = 会话文件路径（回收批注时用）。退出码非 0 时按 `error`/`hint`
  处理：`6 target-unreachable` 先 `curl <target>` 自检网络；`3 dashboard-not-alive`
  按 fenix-dashboard skill 拉起；`4 project-not-registered` 先 `--add-project`。

安全边界（必守）：会话文件只能由本脚本（本机磁盘写入）注册，HTTP 通道不提供
「注册任意 URL」入口——**不要**手工往 session.json 写第三方 URL 后引导用户访问；
target 限 http/https，代理只访问注册 target。

## 2. 用户批注

把 wrapper 地址交用户（地址纪律见下），告知：

- 顶栏可**重载**；批注面板默认「批注模式」，点选任意区块即选中（无需页面预置锚），
  也可切「浏览模式」正常操作页面后回到批注位置。
- 每条批注自动记录：CSS selector 锚、文本、轮次、所在页面路径（`page` 字段——
  SPA 页内路由跳转后批注仍能定位到具体视图）。
- 面板「已提交意见」实时列出服务器全部批注（含历史轮次与其他页面条目），每条可
  **编辑**（只改文本，锚/轮次不动，列表标「已编辑」）与**删除**（确认后即删，
  服务器同步）。
- 「导出批注」仅在批注通道不可用时给出本地 JSON 兜底；正常情况批注实时落盘。

**对外交付地址纪律（MUST）**：127.0.0.1 地址禁交用户；一律把
`http://127.0.0.1:8787` 换成 `http://home.icyfenix.cn:8787`（frp 隧道透传，纯
HTTP 无 TLS，**禁用 https**），路径与 `?proto_round=N` 参数不变。交付前用公网地址
端到端探测一次（wrapper 与代理入口 HTTP 200）；隧道不可达时退回「SSH 隧道指向
dashboard 端口」方案并向用户明示备用地址。

## 3. 回收批注

用户告知批注完成后读 `<项目根>/.fenix/ui-debug/<session>/feedback.json`
（`json.dumps(ensure_ascii=False, indent=2)` 形态，`{"feedback": [...]}`）：

- 每条含 `id`（`fb-<毫秒>-<hex6>`，删除/重编辑寻址键）/`anchor`（CSS selector）/
  `text`（批注意见）/`page`（代理内路径）/`round`/`timestamp`/`element`（tag+文本
  快照）；改过的条目另有 `edited`（重编辑时间戳）。历史无 `id` 条目在任何一次列表
  读取时自动补发迁移。
- selector 重放定位：代理入口 URL + `page` 路径打开页面后
  `document.querySelector(anchor)` 即目标元素；`anchor` 里 `:nth-of-type` 链对
  动态列表可能漂移，结合 `element.text` 快照人工确认。
- 整理为问题清单 / 功能需求清单：按 `page` 分组、按轮次区分新旧意见；存在歧义
  （如「这里样式不对」无具体指向）先列出让用户澄清，不要猜。

## 4. 迭代闭环

- **能修**：问题属当前仓库管辖 → 走 fenix-new 立 SPEC（附批注清单作为需求输入，
  `page`+`anchor` 作为验收定位）；属外部系统 → 产出批注报告交对方。
- **复看**：改动落地后 `--round N+1` 重跑注册脚本（同 session 覆盖），用户刷新
  wrapper 即看新版；旧批注按轮次保留，新意见落新轮次。
- 用户明示「批注完成/没有更多意见」时收尾：汇总全部批注的处理结果
  （已修/转 SPEC/不处理+原因），不静默丢弃任何一条。

## 错误与边界

- 目标页是 **SPA 且强依赖 POST/PUT 写接口**：代理只透传 GET/HEAD（读只浏览），
  页面的提交类操作会收 405——批注环只需要「看 + 批」，写操作不可用属预期，
  向用户说明即可。
- 上游不可达 / 返回非 200：代理回 502，注册脚本退出码 6 带自检 hint；会话文件
  已落盘，target 恢复后用户刷新即可，无需重跑脚本。
- 会话名即目录名，须单段路径且无「.」「..」组件（脚本会校验，非法退出码 2）。
- 原型批注（fenix-prototype）通道不受本 skill 影响：`/proto/` 路由与
  `/api/proto/` 落盘行为不变。
