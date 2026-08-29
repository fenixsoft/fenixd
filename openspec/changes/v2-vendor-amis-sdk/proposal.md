## Why

dashboard v2 重构的第一步:AMIS 6.13.0 SDK 的静态产物必须 vendor 进 `static/v2/`,后续所有 v2 SPEC 都依赖 `/v2/sdk.js` 等资源路径。环境可能无外网,故不能运行期从 CDN 拉取(设计文档:2026-08-29-amis-dashboard-v2-design.md,决策表「SDK 引入」)。

## What Changes

- 新增 `core/dashboard/static/v2/` 目录,放入 AMIS 6.13.0 的 5 个静态产物:`sdk.js`、`sdk.css`、`dark.css`、`iconfont.css`、`helper.css`
- 后端零改动:server.py 现有静态 fallback(server.py:231)自动服务 `/v2/*`,本 SPEC 验证其可用

## Capabilities

### New Capabilities
- `v2-sdk-vendor`: AMIS SDK 静态产物 vendor 到 static/v2/ 并可经现有 dashboard 服务访问

### Modified Capabilities

## Impact

- 新增文件:`core/dashboard/static/v2/{sdk.js,sdk.css,dark.css,iconfont.css,helper.css}`(约 3-5MB)
- 不修改任何后端代码;不修改老版 static 文件
