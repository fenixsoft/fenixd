# dashboard 静态产物不得被单测就地改写（主树 dist/index.html 污染面）

## 背景

2026-11-10 凌晨，主树 dashboard 首页打开只剩 `<html><body>rebuilt</body></html>` 占位，
服务进程与 API 全部健康。排查确认是单测把测试替身写进了线上服务直接读盘的主树构建产物，
且 verify 前的 dist 新鲜度探针按 mtime 判「新鲜」直接放过，污染穿透到下一次真实构建才可能自愈。

## 结论（当前生效的事实）

- dashboard 服务（systemd `fenix-dashboard.service`，端口 8787）直接读盘 serve 主树
  `core/dashboard/static/dist/`；该目录是 gitignored 构建产物，但**线上实例与测试共用同一份**，
  不存在构建隔离层。
- `tests/conftest.py` 的 `server_fx` 夹具把仓库 `core/dashboard/static` 原样作为 static_dir
  传给 `DashboardHTTPServer`；凡在 `server_fx` 上就地写 `dist/index.html` 的用例都会污染线上服务。
- `TestBundleRevHeader._seed_dist_index` 的还原义务必须覆盖「index.html 已存在」形态：
  快照原字节、teardown 回写原字节。只处理「缺席→种入→删除」缺席分支，
  真实的 dist 会被 `test_bundle_rev_flips_after_rebuild` 写下的 `rebuilt` 占位永久覆盖。
- verify 开跑前的 dist 新鲜度探针（见 verify-pipeline/serving-dist-freshness-probe）按 mtime
  比较 static src 树与 `dist/index.html`：测试替身写入使 dist 的 mtime **变新**，
  探针判「新鲜」直通、绝不自愈；污染因此可贯穿整轮验证。
- 复原口径：`cd core/dashboard/static && npm run build`（max build + tailwind prebuild），
  正常产物 index.html 约 411 B，引用 `./umi.93ddf611.css`、`./preload_helper.994f8b67.js`、
  `./umi.86bfdeca.js`；`curl http://localhost:8787/` 应返回该 HTML。

## 证据

- 占位字面量来源：`tests/test_dashboard_api.py` `test_bundle_rev_flips_after_rebuild`
  （写入 `<html><body>rebuilt</body></html>`）。
- 事故时刻：`core/dashboard/static/dist/index.html` mtime 2026-11-10 00:05（daemon 全量回归窗口），
  `curl http://localhost:8787/` 返回占位 HTML。
- 修复 commit：`179053166`（`tests/test_dashboard_api.py` 夹具快照回写原字节）；
  回归后 `tests/test_dashboard_api.py` 169 passed，dist/index.html sha256 前后一致。
- 浏览器复核：`http://localhost:8787/#/overview` 正常渲染 7 项目概览，0 console error。
