## ADDED Requirements

### Requirement: 老版 dashboard 与 v2 壳并存不受影响（确定性回归）

`GET /` 老版入口页在停留于老版文档时，`#main` 与 `#btn-overview` 必须可见且正常渲染；随后切换到
`/v2/index.html#/overview` 时 v2 壳 `#root` 正常渲染；两文档各自独立，无整页跳出、无字体 404、无控制台错误。

#### Scenario: 老版页停留时元素可见

- **WHEN** 直接访问 `GET /`（不立即跳转）并等待 `#main` 可见
- **THEN** `#btn-overview` 可见、`#main` 可见（老版 dashboard 正常渲染）

#### Scenario: 切换至 v2 壳各自正常

- **WHEN** 在老版停留断言后切到 `/v2/index.html#/overview`
- **THEN** v2 壳 `#root` 可见，且全程无 404 / 控制台错误（`fixNavHrefs` 已使导航为 hash 形态，不整页跳离）
