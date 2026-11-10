# Dashboard 前端冒烟三则：hash 入口 / 路由不热载 / PrismLight 轻量接入先例

## 背景

2026-11-10 add-project-home-tab 五点增强批次（bento 帧统一 / md 管线渲染 / PrismLight 代码高亮行号 / 图片 raw 直显 / 纯文本兜底）实现与浏览器冒烟中确认的三条可复用事实。

## 结论

- **hash 路由入口必须带 `/#/`**：dashboard 前端为 hash 路由（如 `http://127.0.0.1:8787/#/projects/fenixd?tab=home`）。直接访问路径形态 `/projects/fenixd` 会让 dist/index.html 的 `./umi.*.js` 相对资源引用解析成 `/projects/umi.*.js` → css/js/preload_helper 全 404 白屏（console 三条资源错误）。playwright 冒烟从 `about:blank` goto 正确 hash 入口即可。
- **`?path=` seed 仅挂载时消费一次**：`list.tsx:1714-1718` `useState(() => initialFilters.tab === 'home' ? searchParams.get('path')...)`——同页 hash 变更（不 remount）不会重新解析 seed；直达深链冒烟必须整页加载。文件型 seed 会先 `GET list?path=<文件>` 得 404（list 仅目录）再回退父目录 + 文件选中，console 里那条 404 资源日志是预期行为非故障。
- **dashboard daemon Python 路由不热载**：前端 dist 每请求从盘读（重建即时生效），但 `core/dashboard/routes/*.py` 路由表进程内持有——新增路由（如 `/api/project-files/raw`）必须 kill + 重启 daemon（`FENIX_DASHBOARD_DETACH=1 nohup python3 bin/fenix_dashboard.py --serve`）才生效，否则得到泛化 `{"error": "Not Found"}`。

## react-syntax-highlighter PrismLight 接入先例

首屏 chunk（list.tsx 链）要用 `PrismLight` + `registerLanguage` 显式注册语言集（本批 38 语言，ProjectCodeBlock.tsx REGISTERED 数组），禁止 `import { Prism }` 全量构建进首屏——claude-msg 的全量 Prism 在独立异步 chunk（dist 3173.async.js）可照旧。未知语言安全：refractor try/catch 回退纯文本，`language='text'` 短路。语言模块自包含依赖链（refractor/lang/cpp.js 自带 import c.js），注册顺序无约束。`.vue` 无专属语法映射 `markup`。

## 证据

core/dashboard/static/dist/index.html（`./umi.*` 相对引用）；core/dashboard/static/src/pages/projects/list.tsx:1714-1718、2290；core/dashboard/static/src/pages/projects/components/{ProjectHomeTab.tsx,ProjectCodeBlock.tsx}；冒烟截图 .history/home-tab-*.png（2026-11-10）。
