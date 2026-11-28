# 2026-11-28 立项结论：fenix-ui-debug 任意 URL 界面调试批注环

## 结论

fenix-ui-debug skill 已实现：把任意 http(s) URL 的活页面接入 dashboard 批注框架。
目标页经 dashboard 内反向代理搬到同源下注入批注器，批注复用 prototype_io 落盘。
改动全部落在 dashboard 与 skills 层，未引入新进程、新端口、新依赖。

## 设计要点（为何是反向代理）

- 任意 URL 批注必须把目标页搬到 dashboard 同源下（annotator 的 CSP/事件注入假设）。
  iframe 直载受 X-Frame-Options/CSP 限制；一次性抓取+`<base>` 改写会破坏 SPA 的
  `/api/` 相对 fetch（跨源 CORS）；代理是唯一通用解，且延续「dashboard 单进程
  承载、一条隧道全覆盖、零生命周期」哲学。
- 安全边界：session.json（`<project>/.fenix/ui-debug/<session>/`）只能由本机
  skill 脚本写入，HTTP 通道无「注册任意 URL」入口 → 不构成开放代理；scheme 白
  名单 http/https；target 路径拒绝 `.`/`..` 点段；代理只透传 GET/HEAD（读只
  浏览；目标页写请求 405 属预期，SKILL.md 已披露）。

## 路由面（全部在 core/dashboard/routes/）

- `GET /uidebug/<project>/<session>` = wrapper 页（顶栏+iframe，无尾斜杠也可，
  不 301）；
- `GET /uidebug/<project>/<session>/~/<path>` = 反向代理（sub_path 保留原始
  percent-encoding 不 unquote/re-quote；query 经 parse_qsl 语义化往返，原始形态
  断言须用 handler 记录的 self.path）；
- `GET /uidebug-assets/annotator.js` = 伺服 skills/fenix-prototype/assets/
  annotator.js（单源复用，未复制）；
- `POST /api/uidebug/<project>/<session>/feedback` = 复用
  prototype_io.append_feedback（`/api/` 前缀硬约束不变）。

## 同源改写（rebase）经验

- 三层：静态 HTML 属性（src/href/action/poster/srcset/style，仅根相对 `/` 值）+
  运行时补丁脚本（fetch/XHR/EventSource/history/window.open + 元素属性 setter +
  MutationObserver 兜 innerHTML）+ CSS url()/@import。
- 豁免前缀：代理前缀自身、`/uidebug*`、`/api/uidebug/`——豁免即幂等，重复改写
  无害。
- `<base>` 标签必须剥除；30x 不在服务端跟随，Location 同源改写后原状态码交
  浏览器（urlopen 探测时自动跟随仍落代理通道）；上游头最小化 + 剥 CSP/
  X-Frame-Options；恒 no-store。
- annotator POST 用 `window.__fenixUidDebugNative.fetch`（补丁备份的原生 fetch）
  兜底，防目标应用再包装 fetch。

## uidebug 模式下的批注器差异（annotator.js 单文件双模式）

`window.__FENIX_ANNOTATOR_MODE__="uidebug"` 开关：端点从 pathname
`^/uidebug/([^/]+)/([^/]+)(?:/|$)` 推导；锚=任意元素（CSS selector：唯一 id 截断
链，否则 body→element 的 tag:nth-of-type 链）；annotation 增 `page` 字段=代理内
pathname（SPA 页内路由可定位）。原型模式行为零变化（109 项原型回归守卫）。

## 入口文档约定（--url 末段拆分）

`http://h:3000/app/page2` → target `http://h:3000/app` + entry `page2.html`（
session.json 增 entry 字段，wrapper iframe 直开入口）；`http://h:3000/` → 整站。
query 不继承。单源在 core/dashboard/uidebug_io.py：split_target_url/
normalize_target（点段拒绝）/normalize_entry/write_session/load_session。

## skill 脚本契约（skills/fenix-ui-debug/scripts/uidebug_serve.py）

镜像 proto_serve.py：不自行拉起 dashboard；端口候选链 --dashboard-port >
~/.config/fenixd/dashboard.yaml port: > 8787；realpath 匹配 /api/projects 注册
名；先落盘 session.json 再端到端验证 wrapper+代理入口；退出码 0/2 输入错/3
dashboard 不存活/4 项目未注册/5 wrapper 验证失败（版本过旧）/6 target 不可达
（502 或上游非 200）/1 工具自身异常（stderr ok:false JSON）。

## 测试与真机验证口径

- tests/test_dashboard_uidebug_routes.py：42 项（纯函数+路由守卫+进程内 mini
  upstream 端到端+落盘）；原型回归 109 项；全量 1058 passed（唯一失败
  test_probe_ok_hermetic 为环境性预存：本 harness shell 无 ANTHROPIC 凭据，
  HEAD 干净 worktree 同样失败）。
- 真机：demo 站 http.server 39001 → 注册 → 代理改写/注入/轮次/子页/POST 全通；
  公网 http://home.icyfenix.cn:8787 三通道 200 + 公网 POST 落盘成功
  （2026-11-28 用户级约定修订：公网入口端口 18787 → 8787，与 dashboard
  端口一致）。另：批注 dashboard 自身页面已验证可行——SPA 的 GET API 经
  rebase 正常透传；SSE `/api/stream` 是致命坑（响应头即到、正文永不 EOF、
  心跳保活令 socket timeout 永不触发，代理线程被无限钉死）——fetch_upstream
  按 event-stream 响应头短路空体 + 读体分块加 60s 总时限 + 路由层 204
  快速失败，三层防护缺一不可。

## 教训（并发会话仓库的 git 操作）

- 本仓库常有并发 fenix 会话在提交（wip-overlap gate hook 会自动 stash 保护
  重叠 WIP）。对指定路径 `git stash push` 的 stderr 不可吞（本次 push 实际失败
  而被 `2>/dev/null` 隐藏），随后无参 `git stash pop` 会误应用并发会话的
  stash@{0}。恢复：确认并发会话已把 staged 工作提交（reflog 找 c7e7c3161）后
  `git checkout HEAD --` 还原误应用文件；hook 生成的 stash 条目属并发会话，
  勿 drop。本树禁用 stash 实验，基线验证改用临时 `git worktree add`。

## round 1 修复追加（2026-11-28 dashboard 自身批注）

三条批注（设置页左菜单列布局+背景、右面板列背景）已修复并经浏览器双档验证
（`core/dashboard/static/src/pages/settings/index.tsx`）：

- 「纯黑与当前背景一致」的实现口径：卡根/两列/Menu 本体 `background:
  'transparent'` 贯穿透出页面基底（深档 #151517、浅档白），浅档渲染零变化、
  无需按档条件化；禁硬编码 #000（ui-theme 纪律）。
- **新坑**：antd Menu 组件自带 colorBgContainer 底色——只透明化容器列不够，
  Menu 本体必须一并 transparent（浏览器截图对比抓出）。
- 菜单列弹性宽：`width: '15%'` + `maxWidth: 224`（原固定宽转上限）+
  `minWidth: 70`（5×14px 汉字宽）；卡体 paddingLeft 归零使菜单贴内容左缘
  （右面板自带 paddingLeft 24 不受影响）。
- 验证口径：playwright 驱动真实深档（localStorage `fenix.theme=dark`——
  embed=1 时主题走 URL 参数且锁定，代理页未带 embed=1 走 localStorage），
  断言 computed backgroundColor + 截图目检；浅档逐字节零变化。

## round 2 修复追加（2026-11-28 dashboard 自身批注续）

- 「SPEC 数」列改显总数（活跃+归档）：`core/dashboard/data/summary.py`
  project_summary 并入 `parse_archived_state(proot)`（STATE.archive.md，
  缺失=空常态分支），仅并计数——status_counts/task 等其余统计仍活跃口径。
  原语义被 tests/test_archive_state_migration.py::test_overview_counts_active_only
  钉死（迁出不计入），已按新口径改名 test_overview_spec_count_total 并断言
  总数（=2）。fenixd 实测 49 活跃+565 归档=614。
- UpdatePanel 动作行（立即检查等）右对齐：antd Space 默认 inline-flex 收缩
  贴左，改 `{ display: 'flex', justifyContent: 'flex-end' }` 推到面板右缘。
- 验证坑：uidebug 代理页里批注面板默认「批注模式」的遮罩会拦截真实点击，
  Playwright 驱动页签切换前必须先点「浏览模式」；且前端文案随浏览器 locale
  变英文（断言按按钮 data-testid 或双语兜底）。

## 批注功能自身优化（2026-11-28：管理能力 + Shadow DOM 样式隔离）

用户反馈两点：批注没有删除/重新编辑；批注 UI 受宿主页样式影响（dashboard 深色
主题下按钮文字变白不可读）。均已落地，原型（/proto/）通道零变化。

- **批注管理（仅 uidebug 模式）**：`core/dashboard/uidebug_io.py` 新增
  `new_feedback_id()`（`fb-<ms>-<hex6>`）、`_mutate_feedback(proto_dir, mutate)`
  （锁内读-改-写：先 feedback_file_lock 再 prototype_io.FEEDBACK_THREAD_LOCK，
  形态分派与 append 同口径，mutate 返回 True 才落盘）、`load_feedback(proto_dir)`
  （惰性给历史无 id 条目补 id 并落盘；**坑：其返回值「missing」有文件缺失与无需
  迁移两义，须按 target.is_file() 判空列表**）、`update_feedback_text`（只改
  text+补 edited 时间戳）、`delete_feedback`。prototype_io.py 导出公共别名
  `FEEDBACK_THREAD_LOCK`/`isolate_corrupt_feedback` 供跨模块复用。
- 路由三通道（static_routes.py）：GET feedback（`load_feedback` 列表）、POST 带
  `{id,text}` 更新 / 无 id 追加（服务端补 id 响应回带）、DELETE `?id=`（**坑：
  query 是 parse_qs 形态，值为 list，取 `(query.get("id") or [""])[0]`**——
  按标量 str 判会恒 400）。守卫复用 `_uidebug_feedback_dir`（session 段校验+
  目录圈定项目根内）。
- annotator.js（skills/fenix-prototype/assets/ 单源，双模式共享）：面板改挂
  **Shadow DOM**（`shadowHost.attachShadow({mode:"open"})` try/catch 降级光 DOM；
  host 元素显式重置可继承属性 `color/font`——宿主深色主题的 body/button 配色
  穿透 shadow 边界的通道只剩继承）；`:host{all:initial}` 兜底；表单元素不继承
  字体，`.fpa-btn`/`.fpa-input` 补 `font:inherit;color:#333`（深色宿主下按钮
  文字不可读的根因=继承宿主 color:#fff）。事件从 shadow 冒出 target 重定向为
  host：点选拦截在 preventDefault 前排除 `ev.target === shadowHost`，
  resolveAnchor uidebug 分支排除 host 元素。面板「已提交意见」在 uidebug 模式
  改为服务器列表真相源（GET 整表渲染，含编辑/删除按钮；提交/更新/删除成功后
  整表刷新），原型模式仍走本会话内存态。
- 测试：tests/test_dashboard_uidebug_routes.py 增 TestFeedbackManageApi 10 项
  （空列表/追加带 id/历史迁移/更新只改 text+edited/更新 404/400/删除/dict 形态
  保留 round/守卫 403 404）。真机 playwright 端到端：深色主题（body
  rgb(21,21,23)+白字）下面板按钮 color rgb(51,51,51) 白底可读；提交→编辑（
  textarea 回填、按钮变「更新批注」、列表标「已编辑」）→删除（confirm 接受后
  列表回 5、状态「已删除批注。」）全链路通，服务器侧真实批注无损。
- **playwright 验证坑**：shadow host 是 0×0 空 div，`waitForSelector('#fpa-root')`
  默认等 visible 会超时，须 `{ state: 'attached' }`；页面级 `page.on('dialog')`
  接受 confirm 后 playwright-cli 的 modal 记账可能残留「already handled」报错，
  属工具侧口径非产品缺陷。
