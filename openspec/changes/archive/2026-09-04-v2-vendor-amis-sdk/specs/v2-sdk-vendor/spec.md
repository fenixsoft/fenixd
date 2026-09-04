## ADDED Requirements

### Requirement: AMIS SDK 静态产物落盘 static/v2/

`core/dashboard/static/v2/` 目录必须包含且仅包含 5 个文件:`sdk.js`、`sdk.css`、`dark.css`、`iconfont.css`、`helper.css`(AMIS 6.13.0)。sdk.js 必须是合法 JS(非 HTML 错误页),其余为合法 CSS。

#### Scenario: 文件完整且内容合法
- **WHEN** 检查 `core/dashboard/static/v2/` 目录内容与文件头
- **THEN** 5 个文件存在;sdk.js 头部为合法 JS 代码;体积为 MB 级;5 个文件均无 HTML 内容

### Requirement: 现有 dashboard 服务可访问 /v2/ 静态资源

后端零改动:通过 server.py 现有静态 fallback 访问 `/v2/sdk.js` 返回 200。

#### Scenario: HTTP 可达
- **WHEN** dashboard 服务运行中,`curl -sI http://127.0.0.1:8787/v2/sdk.js`
- **THEN** 返回 `HTTP/1.1 200 OK`,Content-Type 为 JavaScript

#### Scenario: 老版入口不受影响
- **WHEN** dashboard 服务运行中,`curl -sI http://127.0.0.1:8787/`
- **THEN** 返回 200 且服务的是老版 index.html(未被本 SPEC 改动)
