# v2 Vendored SDK

<!-- knowledge: capability=v2-sdk-vendor rev=2
     sources=spec/archive/2026-09-04-v2-vendor-amis-sdk -->

AMIS SDK 的静态产物 vendored 落盘契约：不依赖运行时安装与 CDN，构建产物随库分发。

## 规则

- AMIS 6.13.0 SDK 静态产物落盘 `core/dashboard/static/v2/`，且仅含 5 个文件：`sdk.js`、`sdk.css`、`dark.css`、`iconfont.css`、`helper.css`；`sdk.js` 为合法 JS（MB 级、非 HTML 错误页），其余为合法 CSS。
- 不运行期从 CDN 拉取（环境可能无外网），静态构建产物随库分发。
- 后端零改动：经 dashboard 服务既有静态 fallback 以 `/v2/*` 路径访问（如 `/v2/sdk.js` 返回 200 与 JavaScript Content-Type）；老版入口不受影响。
- 能力退役注记：v1/v2 dashboard 壳已整体移除（根路由直服 v3 SPA 首页），本页规则不再由现行代码承载，仅供追溯。

## 溯源

- 史前复原 — AMIS SDK 静态产物 vendor 到 static/v2/，不依赖运行时安装；构建产物随库分发
- [2026-09-04 2026-09-04-v2-vendor-amis-sdk](spec/archive/2026-09-04-v2-vendor-amis-sdk/) — 固化 5 文件清单与「静态产物落盘 + 既有静态 fallback 可达」契约
- 2026-09-02 git:ea88dd5a — v1/v2 dashboard 壳整体移除（`core/dashboard/static/v2/` 目录删除，根路由 302 到 v3），本能力随壳层退役
- 2026-09-28 audit git:25bd6751 — 根路由改直服 v3 SPA（`/` 直接返回 `dist/index.html`，302 跳转取消），退役注记根路由表述纠偏
