# Dashboard 全站 404:dist/index.html 缺失(2026-11-15)

## 现象
- 用户报「dashboard 进程挂了?」。实测:进程与监听均正常(systemd `fenix-dashboard.service` 常驻,127.0.0.1:8787 在听),但 `/` 与所有页面返回 JSON `{"error": "Not Found"}` 404,公网 `http://home.icyfenix.cn:18787` 同样 404。

## 根因
- `core/dashboard/static/dist/` 中 `index.html` 被删(目录 mtime 2026-11-15 23:20:28,仅此条目消失;JS chunk 保持 04:32 构建产物完好)。dist 为 gitignore 构建产物,git 无法恢复。静态路由以 `dist/index.html` 为根入口,缺失即全站 404——**进程活着也会呈现「挂了」的外观**。

## 处置
- `cd core/dashboard/static && pnpm build`(max build,约 1-2 分钟)重建后全站恢复:本地 `/`、`/#/`(hash 入口,见 page-container-chrome 页)、公网 18787、`/api/config` 均 200。重建期间无需重启 dashboard 进程,静态文件按请求读取。

## 教训
- 排查 dashboard 不可达时先分层:进程/端口 → HTTP 状态码 → dist 产物完整性。`Server: BaseHTTP` + JSON 404 说明服务端健康,问题在静态入口文件。
